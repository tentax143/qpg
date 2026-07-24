from django.db import connection, models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from pgvector.django import VectorField, HnswIndex


class School(models.Model):
    name = models.CharField(max_length=200)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    monthly_token_budget = models.BigIntegerField(default=0)  # 0 = unlimited
    is_active = models.BooleanField(default=True)
    # Set by the superadmin when the school's billing lapses: users still log in (with a
    # dismissible notice) but every AI-generation action is refused until it is cleared.
    billing_period_over = models.BooleanField(default=False)
    # Set by the superadmin to cut AI image generation for this school only. Papers still
    # generate normally; image_based questions simply skip the image step (no image_finder call).
    disable_image_generation = models.BooleanField(default=False)
    access_shared_vector_store = models.BooleanField(default=False)
    # Cumulative usage — persists even after papers are deleted
    total_papers_generated = models.BigIntegerField(default=0)
    total_tokens_used = models.BigIntegerField(default=0)
    total_cost_accumulated = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    # Cumulative count of AI-generated images across this school's papers (one per question
    # carrying an image_prompt). Bumped on each generation; see core.tasks finalize.
    total_images_generated = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ExamPattern(models.Model):
    """
    Unified exam pattern model that combines blueprint and pattern functionality.
    Stores complete exam structure with sections, instructions, and constraints.
    """
    # Basic info
    name = models.CharField(max_length=100)   # e.g. "PT-2", "Half-Yearly"
    description = models.TextField(blank=True)
    subject = models.CharField(max_length=100, default="")
    class_name = models.CharField(max_length=10, default="")

    # Comprehensive pattern structure
    sections = models.JSONField()  # Enhanced structure with instructions and constraints

    # Metadata
    total_marks = models.IntegerField(default=0)
    total_questions = models.IntegerField(default=0)

    # Track source
    PATTERN_SOURCE_CHOICES = [
        ('manual', 'Manual Creation'),
        ('ai_generated', 'AI Generated'),
        ('imported', 'Imported'),
        ('cbse_official', 'CBSE Official'),
        ('one_mark_test', 'One Mark Test'),
    ]
    pattern_source = models.CharField(max_length=20, choices=PATTERN_SOURCE_CHOICES, default='manual')
    ai_prompt = models.TextField(blank=True)  # Store original teacher input for reference

    # Async generation tracking (mirrors QuestionPaper.status / task_id pattern)
    STATUS_CHOICES = [
        ('queued',      'Queued'),
        ('generating',  'Generating'),
        ('done',        'Done'),
        ('failed',      'Failed'),
    ]
    status  = models.CharField(max_length=20, choices=STATUS_CHOICES, default='done')
    task_id = models.CharField(max_length=255, blank=True, null=True)

    # Academic year this pattern was last verified/updated against (e.g. "2025-26")
    sqp_year = models.CharField(max_length=10, blank=True, default='')

    # Timestamps
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Exam Pattern"
        verbose_name_plural = "Exam Patterns"

    def __str__(self):
        return f"{self.name} - {self.class_name} {self.subject}"

    def get_total_marks(self):
        """Calculate total marks from sections.

        A section's own 'marks' is its FULL total — for compound papers
        (e.g. Science = Biology + Chemistry + Physics) the subsections are a
        breakdown that already sums to the section's marks. So we count the
        section marks when present and only fall back to summing subsections
        when the section has no marks of its own. (Adding both double-counts:
        the old code reported 160 for an 80-mark paper.)
        """
        total = 0
        for section in self.sections:
            slots = section.get('question_slots') or []
            if slots:
                # Slot-authored sections: slots are the source of truth.
                total += sum((s.get('marks') or 0) for s in slots if isinstance(s, dict))
                continue
            sec_marks = section.get('marks') or 0
            if sec_marks:
                total += sec_marks
            else:
                total += sum(subsec.get('marks', 0) for subsec in section.get('subsections', []))
        # Slot marks may be fractional; total_marks is an IntegerField.
        return int(round(total))

    def get_total_questions(self):
        """Calculate total questions from sections (see get_total_marks for the
        section-vs-subsection double-count rationale)."""
        total = 0
        for section in self.sections:
            slots = section.get('question_slots') or []
            if slots:
                total += len(slots)
                continue
            # Support both 'questions_count' (new) and 'questions' (legacy CBSE seed data)
            sec_q = section.get('questions_count') or section.get('questions') or 0
            if sec_q:
                total += sec_q
            else:
                total += sum((subsec.get('questions_count') or subsec.get('questions', 0))
                             for subsec in section.get('subsections', []))
        return total

    def save(self, *args, **kwargs):
        if self.sections:
            self.total_marks = self.get_total_marks()
            self.total_questions = self.get_total_questions()
        super().save(*args, **kwargs)

class QuestionPaper(models.Model):
    class_name = models.CharField(max_length=10)   # "11-A"
    subject = models.CharField(max_length=50)      # "Biology"
    pattern = models.ForeignKey(ExamPattern, on_delete=models.CASCADE)
    chapters = models.JSONField()                  # ["4","5","6"]
    difficulty = models.CharField(max_length=20, default="Medium")
    file = models.FileField(upload_to="question_papers/", blank=True, null=True)
    status = models.CharField(max_length=20, default="queued")  # queued/generating/done/cancelled
    task_id = models.CharField(max_length=255, blank=True, null=True)  # Celery task ID
    status_detail = models.TextField(blank=True, default="")  # failure reason / warnings shown to the teacher
    edited_content = models.TextField(blank=True, null=True)  # Store edited content from the editor
    paper_data = models.JSONField(null=True, blank=True)      # Raw generated JSON — used for re-rendering
    # Stored generate_paper_task kwargs (blueprint_id / model_source / additional_context) so a
    # paper that is 'queued' *waiting* behind the user's active generation can be dispatched later
    # by the per-user serial queue — see core.tasks.dispatch_paper / dispatch_next_queued_paper.
    gen_params = models.JSONField(null=True, blank=True)
    cost = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # Track when the paper was last edited

    def __str__(self):
        return f"{self.class_name} - {self.subject} ({self.pattern})"


class AnswerKey(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('generating', 'Generating'),
        ('done', 'Done'),
        ('failed', 'Failed'),
        ('stale', 'Stale'),
    ]

    paper = models.OneToOneField(QuestionPaper, on_delete=models.CASCADE, related_name='answer_key')
    requested_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='requested_answer_keys')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    task_id = models.CharField(max_length=255, blank=True, null=True)
    source_revision_hash = models.CharField(max_length=64, blank=True, default='')
    data = models.JSONField(default=dict, blank=True)
    error_detail = models.TextField(blank=True, default='')
    cost = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Answer key for paper {self.paper_id} ({self.status})"


class Material(models.Model):
    MATERIAL_TYPES = [
        ("textbook", "Textbook"),
        ("notes", "Notes"),
        ("bank", "Question Bank"),
        ("syllabus", "Syllabus"),
        ("reference", "Reference Book"),
    ]

    # Who can see this material (visibility lives ONLY here — chunks join to it, so flipping a
    # material's visibility later takes effect instantly with no re-ingest):
    #   shared        — the superadmin's global store (school is None); seen by schools granted access
    #   private       — owning school only (default for school uploads)
    #   institutional — shared across ALL schools (the cross-school switch; off by default)
    VISIBILITY_CHOICES = [
        ("shared", "Shared (global / superadmin)"),
        ("private", "Private to school"),
        ("institutional", "Shared across all schools"),
        ("store", "Vector store (allocated schools only)"),
    ]

    class_name = models.CharField(max_length=10)
    subject = models.CharField(max_length=50)
    unit = models.CharField(max_length=255, blank=True, null=True)  # CBSE chapter names can be long
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="materials/")
    type = models.CharField(max_length=50, choices=MATERIAL_TYPES)
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default="private", db_index=True)
    metadata = models.JSONField(default=dict)
    school = models.ForeignKey('School', on_delete=models.SET_NULL, null=True, blank=True, related_name='materials')
    # Named vector store this material belongs to (superadmin-managed shared corpora). Set only when
    # a superadmin uploads into a chosen store; visibility is then "store" and the material is seen
    # ONLY by schools the store is allocated to (see core.access.visibility_q). Null = not in a store.
    vector_store = models.ForeignKey('VectorStore', on_delete=models.SET_NULL, null=True, blank=True, related_name='materials')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.class_name} {self.subject} - {self.title}"
from django.db import models

class BlueprintTemplate(models.Model):
    """Template for creating blueprints with predefined question types and structures"""
    name = models.CharField(max_length=100, unique=True)  # e.g. "CBSE English Core", "CBSE Biology"
    subject = models.CharField(max_length=100)
    class_name = models.CharField(max_length=10)
    description = models.TextField(blank=True)
    
    # Enhanced blueprint structure with question types
    blueprint = models.JSONField(default=dict)  # Enhanced structure with question types
    
    # Metadata
    is_default = models.BooleanField(default=False)  # Mark as default template
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['subject', 'class_name', 'is_default']
        ordering = ['subject', 'class_name', 'name']

    def __str__(self):
        return f"{self.name} - {self.class_name} {self.subject}"

class ExamBlueprint(models.Model):
    """Enhanced blueprint model for specific exam configurations"""
    class_name = models.CharField(max_length=10)   # e.g. "11-A", "12-B"
    subject = models.CharField(max_length=100)
    code = models.CharField(max_length=20, blank=True, null=True)  # e.g. "301" for English Core
    
    # Enhanced blueprint structure
    blueprint = models.JSONField(default=dict)
    
    # Template reference
    template = models.ForeignKey(BlueprintTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Metadata
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['class_name', 'subject']

    def __str__(self):
        return f"{self.class_name} {self.subject} ({self.code})"


# ==============================
# User profile for auth features
# ==============================
class UserProfile(models.Model):
    ROLE_SUPERADMIN = 'superadmin'
    ROLE_SCHOOL_ADMIN = 'school_admin'
    ROLE_TEACHER = 'teacher'

    ROLE_CHOICES = [
        ('superadmin', 'Super Admin'),
        ('school_admin', 'School Admin'),
        ('teacher', 'Teacher'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    require_password_change = models.BooleanField(default=True)
    school = models.ForeignKey('School', on_delete=models.SET_NULL, null=True, blank=True, related_name='members')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='teacher')
    allowed_subject = models.CharField(max_length=100, blank=True, null=True)
    # Stamped (throttled to ~once/minute) on every authenticated API request by
    # api.authentication.touch_last_seen — powers the superadmin "Active Users" view.
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)

    @property
    def is_superadmin(self):
        return self.role == self.ROLE_SUPERADMIN

    @property
    def is_school_admin(self):
        return self.role == self.ROLE_SCHOOL_ADMIN

    def __str__(self):
        return f"Profile({self.user.username})"


class UsageEvent(models.Model):
    """Append-only record of one token-consuming operation (one per paper generation).

    The team-usage page aggregates THESE, not live papers, so a teacher's all-time and
    monthly tokens/cost survive paper deletion — mirroring how the School keeps a cumulative
    counter. ``paper_id`` is a plain int (not an FK) because it may point to a since-deleted
    paper; ``school`` is denormalised so usage still attributes correctly if a user later moves.
    """
    KIND_CHOICES = [
        ("generate", "Generate"),
        ("regenerate", "Regenerate"),
        ("rerender", "Re-render"),
        ("edit", "AI Edit"),
        ("answer_key", "Answer Key"),
        ("pattern", "Pattern"),
        ("enrichment", "Chunk Enrichment"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="usage_events")
    school = models.ForeignKey("School", on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="usage_events")
    paper_id = models.IntegerField(null=True, blank=True)   # may reference a since-deleted paper
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default="generate")
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["school", "created_at"]),
        ]

    def __str__(self):
        return f"UsageEvent({self.user_id}, {self.kind}, {self.input_tokens + self.output_tokens} tok)"

    @classmethod
    def record(cls, user, input_tokens=0, output_tokens=0, cost=0, kind="generate",
               paper_id=None, school=None, created_at=None):
        """Create a usage event. Best-effort: resolves the user's school if not given, and never
        raises (callers wrap in try/except, but guard here too so usage tracking can't break
        generation)."""
        try:
            if school is None and user is not None:
                school = getattr(getattr(user, "profile", None), "school", None)
            return cls.objects.create(
                user=user, school=school, paper_id=paper_id, kind=kind,
                input_tokens=int(input_tokens or 0), output_tokens=int(output_tokens or 0),
                cost=cost or 0,
                **({"created_at": created_at} if created_at else {}),
            )
        except Exception as e:  # pragma: no cover - defensive
            print(f"[UsageEvent] Could not record usage: {e}")
            return None


class GeneratedQuestion(models.Model):
    """
    Track generated questions to avoid duplicates across multiple paper generations.
    Stores question text, embedding, and metadata for similarity checking.
    """
    class_name = models.CharField(max_length=10)
    subject = models.CharField(max_length=50)
    chapter = models.CharField(max_length=50, blank=True, null=True)
    question_text = models.TextField()
    question_hash = models.CharField(max_length=64, db_index=True)  # SHA256 hash for quick lookup
    embedding = models.JSONField(null=True, blank=True)  # Store embedding vector for similarity
    question_type = models.CharField(max_length=50, blank=True)
    marks = models.IntegerField(default=1)
    paper_id = models.ForeignKey(QuestionPaper, on_delete=models.CASCADE, related_name='generated_questions', null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['class_name', 'subject', 'chapter']),
            models.Index(fields=['question_hash']),
        ]

    def __str__(self):
        return f"{self.class_name} {self.subject} - {self.question_text[:50]}..."


@receiver(post_save, sender=User)
def ensure_user_profile(sender, instance, created, raw=False, **kwargs):
    # During fixture loads (loaddata sets raw=True) the profile is loaded explicitly —
    # don't auto-create one here or it collides with the fixture's UserProfile.
    if raw:
        return
    # Create profile on first save
    if created:
        UserProfile.objects.create(user=instance)
    else:
        # Ensure profile exists for older users
        UserProfile.objects.get_or_create(user=instance)


# ==============================
# pgvector-backed embedding store
# ==============================
# Replaces the old per-(class,subject,school) ChromaDB collections. One row per text chunk,
# embedded once; a chunk's chapter membership is a many-to-many (ChunkChapter) so a note that
# spans several chapters is stored ONCE and linked to each — no per-chapter duplication.
#
# Two embedding columns because providers have different dimensions and a pgvector column is
# fixed-dim: local Ollama nomic-embed-text = 768, OpenRouter = 2048. Only the column for the
# provider that ingested the chunk is filled. HNSW (ANN) index only on the 768 column —
# pgvector's HNSW/IVFFlat cap is 2000 dims, so the 2048 column uses an exact distance scan
# (fine: queries are always chapter-scoped, so the candidate set is small).
EMBED_LOCAL_DIM = 768
EMBED_OPENROUTER_DIM = 2048


class MaterialChunk(models.Model):
    material = models.ForeignKey('Material', on_delete=models.CASCADE, related_name='chunks',
                                 null=True, blank=True)
    school = models.ForeignKey('School', on_delete=models.CASCADE, related_name='chunks',
                               null=True, blank=True)  # null == shared store
    class_name = models.CharField(max_length=32)   # normalized (embeddings.normalize_label)
    subject = models.CharField(max_length=64)       # normalized
    title = models.CharField(max_length=255, blank=True, default='')
    material_type = models.CharField(max_length=50, default='textbook')
    chunk_index = models.IntegerField(default=0)
    content = models.TextField()
    provider = models.CharField(max_length=20, default='local')
    embedding_local = VectorField(dimensions=EMBED_LOCAL_DIM, null=True, blank=True)
    embedding_or = VectorField(dimensions=EMBED_OPENROUTER_DIM, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    # ── LLM metadata enrichment (core/enrichment.py, docs/CHAPTER_ENRICHMENT_PLAN.md) ──
    # 'body' = ordinary ingested chunk; 'summary' = LLM-written whole-chapter summary stored
    # as an extra chunk (negative chunk_index so it can never splice into a verbatim span).
    kind = models.CharField(max_length=16, default='body', db_index=True)
    # LEGACY (2026-07-15): the content-kind taxonomy and per-chunk language were dropped
    # from the enrichment prompt at the user's request — enrichment now stores only
    # chapter attribution + cleaned actual content + garbled flag + chapter summaries.
    # Kept as columns (summary rows still use content_kinds=["summary"]); re-runs wipe
    # old taxonomy values.
    content_kinds = models.JSONField(default=list, blank=True)
    language = models.CharField(max_length=32, blank=True, default='')
    garbled = models.BooleanField(default=False)     # legacy-font/mojibake extraction noise
    # LLM-cleaned copy, produced ONLY for mixed/noisy chunks (page noise or glued-on
    # book-back questions removed; the kept text stays verbatim). Empty = original is
    # already clean. `content` itself is NEVER mutated — verbatim extracts and answer
    # keys depend on it.
    content_clean = models.TextField(blank=True, default='')
    enriched_at = models.DateTimeField(null=True, blank=True, db_index=True)  # null = not enriched yet

    class Meta:
        indexes = [
            models.Index(fields=['class_name', 'subject', 'school'], name='chunk_css_idx'),
        ] + (
            [HnswIndex(name='chunk_emb_local_hnsw', fields=['embedding_local'],
                       m=16, ef_construction=64, opclasses=['vector_cosine_ops'])]
            if connection.vendor == 'postgresql'
            else []
        )

    def __str__(self):
        return f"chunk[{self.class_name}/{self.subject}] {self.title} #{self.chunk_index}"


class ChunkChapter(models.Model):
    """Many-to-many link: which chapter(s) (normalized unit label) a chunk belongs to."""
    chunk = models.ForeignKey(MaterialChunk, on_delete=models.CASCADE, related_name='chapter_links')
    unit = models.CharField(max_length=255)   # normalized chapter label

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['chunk', 'unit'], name='uniq_chunk_unit'),
        ]
        indexes = [
            models.Index(fields=['unit'], name='chunkchapter_unit_idx'),
        ]

    def __str__(self):
        return f"{self.chunk_id} → {self.unit}"


class ChapterInfo(models.Model):
    """Chapter-LEVEL metadata: ONE kind per (class, subject, chapter). Replaces the
    rejected per-chunk content-kind taxonomy — a prose lesson whose chunks include
    back-exercises and a grammar box is still, as a whole, prose. Written by the
    enrichment pipeline's chapter classifier (core/enrichment.py) from the chapter's
    NAME + summary + a content sample; kind='' means unclassified (fail-open: retrieval
    treats unclassified chapters as matching everything)."""
    KIND_CHOICES = [
        ('prose', 'Prose'),
        ('poem', 'Poem'),
        ('drama', 'Drama'),
        ('supplementary', 'Supplementary'),
        ('grammar', 'Grammar'),
    ]
    class_name = models.CharField(max_length=50)    # normalized, matches MaterialChunk
    subject = models.CharField(max_length=100)      # normalized, matches MaterialChunk
    unit = models.CharField(max_length=255)         # normalized, matches ChunkChapter.unit
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, blank=True, default='')
    classified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['class_name', 'subject', 'unit'],
                                    name='uniq_chapterinfo_key'),
        ]
        indexes = [
            models.Index(fields=['class_name', 'subject'], name='chapterinfo_cls_subj_idx'),
        ]

    def __str__(self):
        return f"{self.class_name}/{self.subject}/{self.unit} → {self.kind or '?'}"


class EnrichmentRun(models.Model):
    """One chunk-enrichment sweep over the stored corpus (superadmin button / backfill).

    The run row is the durable progress record: the launcher counts the material groups it
    queues (total_groups) and every per-material Celery task increments the counters as it
    finishes — so the superadmin page polls THIS row, not Celery's volatile AsyncResult, and
    progress survives page refreshes and worker restarts."""
    STATUS_CHOICES = [
        ('running', 'Running'),
        # Stop button pressed: in-flight work pauses at the next batch boundary and every
        # queued task drains as a no-op (counted in drained_groups). Once all queued tasks
        # are accounted for, the run flips to 'stopped'.
        ('stopping', 'Stopping'),
        ('done', 'Done'),
        ('failed', 'Failed'),
        # Fully drained. Work already done is kept (idempotent), so "resume" = simply
        # start a new run — it re-processes only what is still pending.
        ('stopped', 'Stopped'),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    force = models.BooleanField(default=False)        # re-label already-enriched chunks too
    total_groups = models.IntegerField(default=0)     # materials queued
    done_groups = models.IntegerField(default=0)
    failed_groups = models.IntegerField(default=0)
    drained_groups = models.IntegerField(default=0)   # tasks that no-op'd/aborted due to stop
    chunks_labeled = models.IntegerField(default=0)
    summaries_created = models.IntegerField(default=0)
    garbled_found = models.IntegerField(default=0)
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    cost = models.DecimalField(max_digits=12, decimal_places=4, default=0)
    error_samples = models.JSONField(default=list, blank=True)  # first few error strings
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"EnrichmentRun {self.id} ({self.status} {self.done_groups + self.failed_groups}/{self.total_groups})"


class SchoolVectorLink(models.Model):
    """Cross-school access grant: the `viewer` school may read the `source` school's own
    materials (its private vector store), in addition to its own. Directional — a reciprocal
    link is a separate row. A school can be linked to many sources. Managed by the superadmin.
    Like shared-store access, this is scope-based: no copying, takes effect immediately."""
    viewer = models.ForeignKey('School', on_delete=models.CASCADE, related_name='vector_links_out')
    source = models.ForeignKey('School', on_delete=models.CASCADE, related_name='vector_links_in')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['viewer', 'source'], name='uniq_school_vector_link'),
            models.CheckConstraint(check=~models.Q(viewer=models.F('source')), name='no_self_vector_link'),
        ]

    def __str__(self):
        return f"{self.viewer_id} → {self.source_id}"


class BookContents(models.Model):
    """Parsed table-of-contents of a textbook (from its uploaded prelims/contents PDF).

    Maps each unit → its lessons → printed page number. Used to split the per-unit content PDFs at
    exact page offsets with the book's OFFICIAL lesson titles, instead of heuristic/LLM guessing.
    One row per (class_name, subject, school); the superadmin's global TOC is school=None."""
    class_name = models.CharField(max_length=10)
    subject = models.CharField(max_length=100)
    school = models.ForeignKey('School', on_delete=models.CASCADE, null=True, blank=True,
                               related_name='book_contents')
    title = models.CharField(max_length=200, blank=True, default='')   # e.g. "Poorvi"
    # [{"unit": 1, "theme": "Wit and Wisdom",
    #   "lessons": [{"title": "The Wit that Won Hearts", "page": 1}, ...]}, ...]
    units = models.JSONField(default=list)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['class_name', 'subject']

    def __str__(self):
        return f"TOC {self.class_name}/{self.subject} ({len(self.units or [])} units)"


class VectorStore(models.Model):
    """A named corpus of superadmin-uploaded materials, allocatable to specific schools.

    Generalises the single global 'shared' store (School.access_shared_vector_store) into many
    named ones. Allocation is scope-based (M2M to School): a school allocated a store sees that
    store's materials at retrieval — in addition to its own private + institutional content —
    with NO copying (takes effect instantly, see core.access.visibility_q). Materials in a store
    carry visibility='store' so they never leak via the global shared/institutional clauses."""
    name = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    schools = models.ManyToManyField('School', related_name='vector_stores', blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class SystemNotification(models.Model):
    """System-wide or school-targeted notifications shown as a banner at the top of all pages."""
    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
    ]

    title = models.CharField(max_length=200)
    message = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='info')
    animation_interval = models.IntegerField(default=10, help_text="Scroll animation interval in seconds (higher = slower)")
    is_active = models.BooleanField(default=True, db_index=True)
    # Schools to target (empty = all schools/global notification)
    schools = models.ManyToManyField('School', related_name='notifications', blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.severity})"


class Issue(models.Model):
    """A problem report raised by any user ("this isn't working"). Superadmin triages it
    through the status workflow (open → investigating → fixing → fixed) and can leave a
    note the reporter sees."""
    STATUS_OPEN = 'open'
    STATUS_INVESTIGATING = 'investigating'
    STATUS_FIXING = 'fixing'
    STATUS_FIXED = 'fixed'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_INVESTIGATING, 'Investigating'),
        (STATUS_FIXING, 'Fixing'),
        (STATUS_FIXED, 'Fixed'),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    # Superadmin's reply/note back to the reporter (e.g. "Fixed in today's release").
    admin_note = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='reported_issues')
    school = models.ForeignKey('School', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='issues')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.status})"


class DirectMessage(models.Model):
    """A message a superadmin sends to one specific user. The frontend polls the
    recipient's unread messages and shows them as a toast in the top-right corner;
    dismissing a toast marks it read so it stops appearing."""
    LEVEL_INFO = 'info'
    LEVEL_WARNING = 'warning'
    LEVEL_SUCCESS = 'success'
    LEVEL_CHOICES = [
        (LEVEL_INFO, 'Info'),
        (LEVEL_WARNING, 'Warning'),
        (LEVEL_SUCCESS, 'Success'),
    ]

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='direct_messages')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='sent_direct_messages')
    body = models.TextField()
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES, default=LEVEL_INFO)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
        ]

    def __str__(self):
        return f"DM to {self.recipient_id}: {self.body[:40]}"
