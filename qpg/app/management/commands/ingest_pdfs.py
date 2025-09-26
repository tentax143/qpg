from django.core.management.base import BaseCommand
from app.llm_backend.embeddings import ingest_all_pdfs, ingest_class11_biology, ingest_class11_english

class Command(BaseCommand):
    help = 'Ingest PDFs into the embeddings database for question generation'

    def add_arguments(self, parser):
        parser.add_argument(
            '--subject',
            type=str,
            help='Specific subject to ingest (e.g., biology, english)',
        )
        parser.add_argument(
            '--class',
            type=str,
            dest='class_name',
            help='Specific class to ingest (e.g., 11, 12)',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Ingest all available PDFs',
        )

    def handle(self, *args, **options):
        if options['all']:
            self.stdout.write('Ingesting all available PDFs...')
            total_chunks, total_files = ingest_all_pdfs()
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully ingested {total_chunks} chunks from {total_files} PDF files'
                )
            )
        elif options['subject']:
            subject = options['subject'].lower()
            if subject == 'biology':
                self.stdout.write('Ingesting Class 11 Biology PDFs...')
                chunks = ingest_class11_biology()
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully ingested {chunks} chunks from Biology PDFs')
                )
            elif subject == 'english':
                self.stdout.write('Ingesting Class 11 English PDFs...')
                chunks = ingest_class11_english()
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully ingested {chunks} chunks from English PDFs')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'No specific ingestion function for subject: {subject}')
                )
                self.stdout.write('Use --all to ingest all PDFs')
        else:
            self.stdout.write('No action specified. Use --all to ingest all PDFs or --subject to specify a subject.')
            self.stdout.write('Available subjects: biology, english')
            self.stdout.write('Example: python manage.py ingest_pdfs --all')
            self.stdout.write('Example: python manage.py ingest_pdfs --subject biology')
