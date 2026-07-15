# Backfill ChunkChapter links for chunks whose chapter names normalize to "" under the old
# ASCII-only normalize_label (Indic-script books: Tamil/Hindi/…). Those chunks were ingested
# with NO chapter links, so the unit filter in embeddings.query never matched them and every
# "per-chapter" retrieval silently searched the whole book. normalize_label now preserves
# non-ASCII chars; this migration creates the missing links from each Material's declared
# chapters (metadata["chapters"], falling back to Material.unit).
import re

from django.db import migrations


def _norm(label):
    """Copy of the FIXED core.embeddings.normalize_label — embedded so this migration stays
    self-contained and immune to future changes of the live function."""
    if not label:
        return None
    clean = str(label).lower().replace(" ", "_").replace("-", "_")
    clean = "".join(
        ch for ch in clean
        if not ch.isascii() or ch == "_" or "a" <= ch <= "z" or "0" <= ch <= "9"
    )
    return re.sub(r"_+", "_", clean).strip("_")


def backfill_links(apps, schema_editor):
    Material = apps.get_model("core", "Material")
    MaterialChunk = apps.get_model("core", "MaterialChunk")
    ChunkChapter = apps.get_model("core", "ChunkChapter")

    created_total = 0
    for mat in Material.objects.all().only("id", "unit", "metadata").iterator():
        raw_units = (mat.metadata or {}).get("chapters") or ([mat.unit] if mat.unit else [])
        labels = sorted({l for l in (_norm(u) for u in raw_units) if l})
        if not labels:
            continue
        # Only chunks with NO links at all: ASCII-labelled chunks got theirs at ingestion.
        chunk_ids = list(
            MaterialChunk.objects.filter(material_id=mat.id, chapter_links__isnull=True)
            .values_list("id", flat=True)
        )
        if not chunk_ids:
            continue
        links = [ChunkChapter(chunk_id=cid, unit=u) for cid in chunk_ids for u in labels]
        ChunkChapter.objects.bulk_create(links, batch_size=2000, ignore_conflicts=True)
        created_total += len(links)
    if created_total:
        print(f"[0039] backfilled {created_total} chunk-chapter links")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0038_alter_usageevent_kind"),
    ]

    operations = [
        migrations.RunPython(backfill_links, migrations.RunPython.noop),
    ]
