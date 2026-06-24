"""
Repair vector-store collections whose stored embedding dimension does not match
the local (Ollama) embedding dimension that the query path uses.

Background
----------
Retrieval always queries with the *local* provider (Ollama / nomic-embed-text,
768-dim) against the ``default`` collection. If a ``default`` collection was
populated with vectors of a different dimension (e.g. 2048-dim from the
OpenRouter/nemotron model), every query fails with::

    Embedding dimension 768 does not match collection dimensionality 2048

…so the section gets 0 chars of context and the paper is generated ungrounded.

This command finds every ``default`` collection whose dimension != the local
dimension and RE-EMBEDS its stored chunk text with the local model. The chunk
text, ids and metadata are already stored in the collection, so no PDF is
re-parsed — only the vectors are recomputed with the correct model.

Safe by default: DRY RUN unless ``--apply`` is passed. The command reads all
documents and computes the new vectors *before* it deletes the old collection,
and refuses to overwrite if the new vectors come back empty/all-zero (e.g. if
Ollama is down), so a botched embed can never wipe good data.

Usage
-----
    python manage.py fix_embedding_dims                 # dry-run, scan everything
    python manage.py fix_embedding_dims --apply          # repair
    python manage.py fix_embedding_dims --apply --only 11_chemistry 11_physics
"""

import os
import chromadb
from django.core.management.base import BaseCommand

from core import embeddings


class Command(BaseCommand):
    help = "Re-embed vector-store 'default' collections whose dim != the local (Ollama) dim."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true",
                            help="Actually re-embed. Without this it is a dry run.")
        parser.add_argument("--only", nargs="+", default=None,
                            help="Limit to these subject dir names (e.g. 11_chemistry 11_physics).")
        parser.add_argument("--batch", type=int, default=128,
                            help="Chunks per collection.add() call when writing back.")

    def _peek_dim(self, col):
        peek = col.get(limit=1, include=["embeddings"])
        embs = peek.get("embeddings")
        if embs is not None and len(embs) > 0 and embs[0] is not None:
            return len(embs[0])
        return None

    def handle(self, *args, **opts):
        apply = opts["apply"]
        only = set(opts["only"]) if opts["only"] else None
        batch = opts["batch"]
        base = "vector_store"
        target_dim = embeddings.OLLAMA_DIM                      # 768
        local_name = embeddings.COLLECTION_NAMES["local"]       # 'default'

        if not os.path.isdir(base):
            self.stdout.write(self.style.WARNING("vector_store/ not found — nothing to do"))
            return

        mode = self.style.SUCCESS("APPLY") if apply else self.style.WARNING("DRY-RUN")
        self.stdout.write(f"\n[{mode}] Repairing '{local_name}' collections to local dim={target_dim}\n")

        scanned, flagged, repaired, errors = 0, 0, 0, 0

        for ns in sorted(os.listdir(base)):
            nsdir = os.path.join(base, ns)
            if not os.path.isdir(nsdir):
                continue
            for sub in sorted(os.listdir(nsdir)):
                if only and sub not in only:
                    continue
                subdir = os.path.join(nsdir, sub)
                if not os.path.isdir(subdir):
                    continue
                try:
                    client = chromadb.PersistentClient(
                        path=subdir, settings=chromadb.Settings(anonymized_telemetry=False))
                    col = client.get_collection(local_name)
                except Exception:
                    continue  # no local collection here
                try:
                    cnt = col.count()
                except Exception as e:
                    self.stderr.write(f"  {ns}/{sub}: count failed ({e})")
                    continue
                if cnt == 0:
                    continue
                scanned += 1
                dim = self._peek_dim(col)
                if dim == target_dim:
                    continue
                flagged += 1
                self.stdout.write(self.style.WARNING(
                    f"  {ns}/{sub}: dim={dim} count={cnt}  →  needs re-embed to {target_dim}"))
                if not apply:
                    continue

                # ── read everything, re-embed, then swap ──────────────────────
                try:
                    data = col.get(include=["documents", "metadatas"])
                    ids = data.get("ids") or []
                    docs = data.get("documents") or []
                    metas = data.get("metadatas") or [{} for _ in ids]
                    if not ids or not any((d or "").strip() for d in docs):
                        self.stderr.write(f"      ! no document text stored — cannot re-embed, skipping")
                        errors += 1
                        continue

                    self.stdout.write(f"      re-embedding {len(ids)} chunks via local model…")
                    vectors = embeddings.get_embeddings_batch(docs, provider="local")
                    if (len(vectors) != len(ids)
                            or not vectors
                            or len(vectors[0]) != target_dim
                            or all(all(v == 0 for v in vec) for vec in vectors[:5])):
                        self.stderr.write(self.style.ERROR(
                            "      ! re-embed produced empty/zero/wrong-dim vectors (is Ollama up?) — "
                            "NOT touching the existing collection"))
                        errors += 1
                        continue

                    # Only now is it safe to drop and rebuild.
                    client.delete_collection(local_name)
                    newcol = client.create_collection(name=local_name, metadata={"hnsw:space": "cosine"})
                    for i in range(0, len(ids), batch):
                        newcol.add(
                            ids=ids[i:i + batch],
                            embeddings=vectors[i:i + batch],
                            documents=docs[i:i + batch],
                            metadatas=metas[i:i + batch],
                        )
                    self.stdout.write(self.style.SUCCESS(
                        f"      ✓ rebuilt {ns}/{sub} '{local_name}' at dim {target_dim} ({newcol.count()} chunks)"))
                    repaired += 1
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"      ! repair failed for {ns}/{sub}: {e}"))
                    errors += 1

        self.stdout.write("\n" + "-" * 60)
        self.stdout.write(f"Scanned 'default' collections : {scanned}")
        self.stdout.write(f"Dim mismatches found          : {flagged}")
        if apply:
            self.stdout.write(self.style.SUCCESS(f"Repaired                      : {repaired}"))
            if errors:
                self.stdout.write(self.style.ERROR(f"Errors                        : {errors}"))
        else:
            self.stdout.write(self.style.WARNING("\nDry run — nothing changed. Re-run with --apply to repair."))
