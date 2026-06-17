from django.core.management.base import BaseCommand
from core.models import Subject

CBSE_SUBJECTS = [
    # Languages
    'English Core',
    'English Elective',
    'English Language & Literature',
    'Hindi Core',
    'Hindi Elective',
    'Hindi Course A',
    'Hindi Course B',
    'Sanskrit Core',
    'Sanskrit Elective',
    'French',
    'German',
    'Spanish',
    'Tamil',
    'Telugu',
    'Kannada',
    'Malayalam',
    'Marathi',
    'Punjabi',
    'Urdu',
    # Mathematics
    'Mathematics',
    'Mathematics Standard',
    'Mathematics Basic',
    # Sciences
    'Science',
    'Physics',
    'Chemistry',
    'Biology',
    'Biotechnology',
    # Social Sciences
    'Social Science',
    'History',
    'Geography',
    'Political Science',
    'Economics',
    'Sociology',
    'Psychology',
    # Commerce
    'Accountancy',
    'Business Studies',
    # Technology
    'Computer Science',
    'Informatics Practices',
    'Information Technology',
    # Primary
    'Environmental Studies',
    # Vocational / Other
    'Physical Education',
    'Fine Arts',
    'Painting',
    'Music',
    'Home Science',
    'Entrepreneurship',
    'Legal Studies',
]


class Command(BaseCommand):
    help = 'Seed standard CBSE subjects into the database'

    def handle(self, *args, **options):
        created = 0
        for name in CBSE_SUBJECTS:
            _, was_created = Subject.objects.get_or_create(name=name)
            if was_created:
                created += 1
        skipped = len(CBSE_SUBJECTS) - created
        self.stdout.write(self.style.SUCCESS(
            f'Done. {created} subjects created, {skipped} already existed. Total: {len(CBSE_SUBJECTS)}.'
        ))
