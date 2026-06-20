import os
import shutil
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "One-time migration: move legacy vector_store/{class}_{subject}/ dirs to vector_store/shared/"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would be moved without actually moving anything',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        base = "vector_store"
        shared_base = os.path.join(base, "shared")

        if not os.path.exists(base):
            self.stdout.write(self.style.WARNING("vector_store/ directory not found — nothing to migrate"))
            return

        # Collect directories that look like old-format {class}_{subject} (not prefixed with school_ or named shared)
        moved, skipped = 0, 0
        for name in sorted(os.listdir(base)):
            src = os.path.join(base, name)
            if not os.path.isdir(src):
                continue
            if name == "shared" or name.startswith("school_"):
                self.stdout.write(f"  skip (already namespaced): {name}")
                skipped += 1
                continue

            dst = os.path.join(shared_base, name)
            if os.path.exists(dst):
                self.stdout.write(self.style.WARNING(f"  skip (already exists in shared/): {name}"))
                skipped += 1
                continue

            if dry_run:
                self.stdout.write(f"  [dry-run] would move: {name}  →  shared/{name}")
            else:
                os.makedirs(shared_base, exist_ok=True)
                shutil.move(src, dst)
                self.stdout.write(self.style.SUCCESS(f"  moved: {name}  →  shared/{name}"))
            moved += 1

        if dry_run:
            self.stdout.write(self.style.WARNING(f"\nDry run — {moved} dirs would be moved, {skipped} skipped"))
        else:
            self.stdout.write(self.style.SUCCESS(f"\nDone — {moved} dirs moved to shared/, {skipped} skipped"))
            if moved:
                self.stdout.write(
                    "Run 'resync-vectorstore' from the superadmin UI (or copy_shared_vectorstore_task) "
                    "for any school that should have access to this data."
                )
