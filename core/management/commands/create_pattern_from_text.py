"""
Django management command to create exam patterns from teacher text input.
Uses the new unified pattern system with AI parsing.
"""

import json
import sys
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.models import User
from core.models import ExamPattern
from core.pattern_ai_generator import generate_pattern_from_text


class Command(BaseCommand):
    help = 'Create an exam pattern from teacher text input using AI parsing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--text',
            type=str,
            help='Pattern text input from teacher (in quotes)'
        )
        parser.add_argument(
            '--file',
            type=str,
            help='Path to file containing pattern text'
        )
        parser.add_argument(
            '--class',
            type=str,
            required=True,
            dest='class_name',
            help='Class name (e.g., "7", "8", "10")'
        )
        parser.add_argument(
            '--subject',
            type=str,
            required=True,
            help='Subject name (e.g., "English", "Mathematics")'
        )
        parser.add_argument(
            '--exam',
            type=str,
            default='Default Exam',
            help='Exam name (e.g., "PT-2", "Half-Yearly")'
        )
        parser.add_argument(
            '--name',
            type=str,
            default='',
            help='Pattern name to store in database'
        )
        parser.add_argument(
            '--user',
            type=str,
            default='admin',
            help='Username of the creator'
        )
        parser.add_argument(
            '--save',
            action='store_true',
            help='Save the generated pattern to database'
        )
        parser.add_argument(
            '--preview',
            action='store_true',
            help='Preview the pattern without saving'
        )

    def handle(self, *args, **options):
        # Get teacher input
        teacher_input = options.get('text') or self._get_input_from_file(options.get('file'))

        if not teacher_input:
            raise CommandError('Please provide pattern text using --text or --file')

        class_name = options['class_name']
        subject = options['subject']
        exam_name = options['exam']
        pattern_name = options['name'] or f"{exam_name} - {class_name} {subject}"

        self.stdout.write(
            self.style.SUCCESS(f"\n{'='*60}")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Generating Pattern from Teacher Input")
        )
        self.stdout.write(
            self.style.SUCCESS(f"{'='*60}\n")
        )

        # Show input
        self.stdout.write(self.style.WARNING("Teacher Input:"))
        self.stdout.write(teacher_input)
        self.stdout.write("\n")

        # Generate pattern using AI
        self.stdout.write(self.style.WARNING("Generating pattern using AI..."))
        try:
            pattern_data = generate_pattern_from_text(
                teacher_input=teacher_input,
                class_name=class_name,
                subject=subject,
                exam_name=exam_name
            )
            self.stdout.write(self.style.SUCCESS("✓ Pattern generated successfully\n"))
        except Exception as e:
            raise CommandError(f"Error generating pattern: {str(e)}")

        # Show generated pattern
        self.stdout.write(self.style.WARNING("Generated Pattern Structure:"))
        self.stdout.write(json.dumps(pattern_data, indent=2))
        self.stdout.write("\n")

        # Show summary
        self._show_pattern_summary(pattern_data)

        # Save if requested
        if options['save'] or options['preview'] is False:
            try:
                user = self._get_or_create_user(options['user'])
                pattern = ExamPattern.objects.create(
                    name=pattern_name,
                    description=f"Auto-generated from teacher input",
                    subject=subject,
                    class_name=class_name,
                    sections=pattern_data['sections'],
                    total_marks=pattern_data['total_marks'],
                    total_questions=pattern_data['total_questions'],
                    pattern_source='ai_generated',
                    ai_prompt=teacher_input,
                    created_by=user
                )
                self.stdout.write(
                    self.style.SUCCESS(f"\n✓ Pattern saved to database (ID: {pattern.id})")
                )
                self.stdout.write(
                    self.style.SUCCESS(f"Pattern Name: {pattern.name}")
                )
            except Exception as e:
                raise CommandError(f"Error saving pattern: {str(e)}")

        self.stdout.write(
            self.style.SUCCESS(f"\n{'='*60}")
        )
        self.stdout.write(self.style.SUCCESS("Pattern creation completed!"))
        self.stdout.write(
            self.style.SUCCESS(f"{'='*60}\n")
        )

    def _get_input_from_file(self, file_path):
        """Read teacher input from file"""
        if not file_path:
            return None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            raise CommandError(f"File not found: {file_path}")
        except Exception as e:
            raise CommandError(f"Error reading file: {str(e)}")

    def _show_pattern_summary(self, pattern_data):
        """Display a summary of the generated pattern"""
        self.stdout.write(self.style.WARNING("Pattern Summary:"))
        self.stdout.write(
            f"  Total Marks: {pattern_data.get('total_marks', 'N/A')}"
        )
        self.stdout.write(
            f"  Total Questions: {pattern_data.get('total_questions', 'N/A')}"
        )
        self.stdout.write(f"  Sections: {len(pattern_data.get('sections', []))}")

        for idx, section in enumerate(pattern_data.get('sections', []), 1):
            self.stdout.write(
                f"    {idx}. {section.get('name', 'Unknown')} - "
                f"{section.get('marks', 0)} marks, "
                f"{section.get('questions_count', 0)} questions"
            )

            if section.get('instructions'):
                for instr in section['instructions']:
                    self.stdout.write(f"       • {instr}")

            if section.get('subsections'):
                for subsec in section['subsections']:
                    self.stdout.write(
                        f"       ├─ {subsec.get('name', 'Unknown')} - "
                        f"{subsec.get('marks', 0)} marks"
                    )

    def _get_or_create_user(self, username):
        """Get or create a user"""
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(
                self.style.WARNING(f"User '{username}' not found. Creating admin user...")
            )
            user = User.objects.create_superuser(
                username=username,
                email=f"{username}@example.com",
                password="default_password"
            )
        return user
