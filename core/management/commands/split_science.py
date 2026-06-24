"""
Split class 11/12 materials uploaded under the umbrella subject "Science" into
the three subjects CBSE actually examines from class 11 onwards — Physics,
Chemistry, and Biology.

For every matching Material it:
  1. classifies the chapter (Material.unit / title) via core.data.science_split,
  2. moves that chapter's vector-store chunks from the  {class}_science
     collection to the {class}_{physics|chemistry|biology} collection
     (in the same namespace — the school's private store, or shared), and
  3. updates Material.subject.

Safe by default: runs as a DRY RUN unless --apply is passed. Ambiguous or
unmatched chapters (e.g. "Thermodynamics", which exists in both Physics and
Chemistry) are NEVER moved — they are listed for manual handling.

Usage
-----
    python manage.py split_science                  # dry-run, classes 11 & 12, all schools
    python manage.py split_science --apply           # actually migrate
    python manage.py split_science --school 1 --apply
    python manage.py split_science --classes 11 12 --apply
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Material
from core.data.science_split import classify_chapter
from core import embeddings


class Command(BaseCommand):
    help = "Split class 11/12 'Science' materials into Physics / Chemistry / Biology (DB + vector store)."

    def add_arguments(self, parser):
        parser.add_argument("--classes", nargs="+", default=["11", "12"],
                            help="Class names to process (default: 11 12).")
        parser.add_argument("--school", type=int, default=None,
                            help="Limit to a single school id (default: all schools).")
        parser.add_argument("--apply", action="store_true",
                            help="Actually write changes. Without this it is a dry run.")

    # ── vector-store migration for one chapter ────────────────────────────────
    def _move_chunks(self, class_name, unit, old_subject, new_subject, school_id, apply):
        """Move one chapter's chunks across every provider collection.

        Returns the number of chunks moved (or that would be moved in dry-run).
        """
        cls_norm = embeddings.normalize_label(class_name)
        old_norm = embeddings.normalize_label(old_subject)   # "science"
        new_norm = embeddings.normalize_label(new_subject)
        unit_norm = embeddings.normalize_label(unit)
        moved = 0

        for provider in embeddings.COLLECTION_NAMES:
            try:
                src = embeddings.get_collection(class_name, old_subject, provider, school_id=school_id)
                res = src.get(where={"unit": unit_norm},
                              include=["documents", "embeddings", "metadatas"])
            except Exception as e:
                self.stderr.write(f"      ! {provider}: read failed ({e})")
                continue

            ids = res.get("ids") or []
            if not ids:
                continue
            moved = max(moved, len(ids))
            if not apply:
                continue

            docs = res.get("documents") or []
            embs = [list(e) for e in (res.get("embeddings") or [])]
            metas = res.get("metadatas") or []
            for m in metas:
                m["subject"] = new_norm
            # Anchor the rename to the class prefix so unit names that happen to
            # contain "science" are never touched.
            new_ids = [i.replace(f"{cls_norm}_{old_norm}_", f"{cls_norm}_{new_norm}_", 1) for i in ids]

            try:
                dst = embeddings.get_collection(class_name, new_subject, provider, school_id=school_id)
                # upsert = idempotent (safe to re-run); add the destination BEFORE
                # deleting the source so a crash duplicates rather than loses data.
                dst.upsert(ids=new_ids, embeddings=embs, documents=docs, metadatas=metas)
                src.delete(ids=ids)
            except Exception as e:
                self.stderr.write(f"      ! {provider}: move failed ({e})")
        return moved

    def handle(self, *args, **opts):
        classes = [str(c) for c in opts["classes"]]
        school = opts["school"]
        apply = opts["apply"]

        qs = Material.objects.filter(subject__iexact="Science", class_name__in=classes)
        if school is not None:
            qs = qs.filter(school_id=school)
        qs = qs.order_by("school_id", "class_name", "unit", "id")

        mode = self.style.SUCCESS("APPLY") if apply else self.style.WARNING("DRY-RUN")
        self.stdout.write(f"\n[{mode}] Splitting 'Science' → Physics/Chemistry/Biology  "
                          f"(classes={','.join(classes)}, school={school or 'all'})\n")

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING(
                "No materials found with subject='Science' for those classes/school — nothing to do."))
            return

        planned, unresolved, errors = [], [], []
        # counts[(school_id, class_name, target)] = n_materials
        counts = {}

        for mat in qs:
            chapter = (mat.unit or mat.title or "").strip()
            target, reason = classify_chapter(chapter, mat.class_name)
            if not target:
                unresolved.append((mat, chapter, reason))
                continue
            planned.append((mat, chapter, target, reason))
            key = (mat.school_id, mat.class_name, target)
            counts[key] = counts.get(key, 0) + 1

        # ── execute / preview ────────────────────────────────────────────────
        for mat, chapter, target, reason in planned:
            line = (f"  school={mat.school_id or '-'} class={mat.class_name} "
                    f"[{mat.subject} -> {target}]  {chapter[:50]}")
            try:
                n = self._move_chunks(mat.class_name, chapter, mat.subject, target,
                                      mat.school_id, apply)
            except Exception as e:
                errors.append((mat, str(e)))
                self.stderr.write(self.style.ERROR(f"{line}  -- vector move ERROR: {e}"))
                continue

            if apply:
                with transaction.atomic():
                    mat.subject = target
                    mat.save(update_fields=["subject"])
                self.stdout.write(self.style.SUCCESS(f"{line}  ({n} chunks moved)"))
            else:
                self.stdout.write(f"{line}  (~{n} chunks)")

        # ── unresolved (left as Science) ──────────────────────────────────────
        if unresolved:
            self.stdout.write(self.style.WARNING(
                f"\n{len(unresolved)} chapter(s) left UNCHANGED (ambiguous / unmatched — handle manually):"))
            for mat, chapter, reason in unresolved:
                self.stdout.write(f"  school={mat.school_id or '-'} class={mat.class_name} "
                                  f"id={mat.id}  {chapter[:50]}  [{reason}]")

        # ── summary ───────────────────────────────────────────────────────────
        self.stdout.write("\n" + "-" * 60)
        self.stdout.write(f"Materials scanned : {total}")
        self.stdout.write(f"Classified        : {len(planned)}")
        self.stdout.write(f"Unresolved        : {len(unresolved)}")
        if errors:
            self.stdout.write(self.style.ERROR(f"Errors            : {len(errors)}"))
        self.stdout.write("By target subject :")
        for (sid, cls, target) in sorted(counts):
            self.stdout.write(f"    school={sid or '-'} class={cls}  {target}: {counts[(sid, cls, target)]}")

        if not apply:
            self.stdout.write(self.style.WARNING(
                "\nDry run — nothing was changed. Re-run with --apply to perform the migration."))
        else:
            self.stdout.write(self.style.SUCCESS("\nDone."))
