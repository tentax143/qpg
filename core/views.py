from django.shortcuts import render, redirect, get_object_or_404
from .models import QuestionPaper, ExamPattern, Material, BlueprintTemplate, ExamBlueprint
from . import embeddings
from django.http import JsonResponse
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST
import json
import docx
import os
import tempfile


@login_required(login_url='login')
def dashboard_view(request):
    # Ensure default model provider is AWS unless user switches
    if 'model_choice' not in request.session:
        request.session['model_choice'] = 'aws'
    # Admin sees all; regular users see only their own
    if request.user.is_superuser or request.user.is_staff:
        papers = QuestionPaper.objects.all().order_by("-created_at")[:10]
    else:
        papers = QuestionPaper.objects.filter(created_by=request.user).order_by("-created_at")[:10]
    return render(request, "dashboard.html", {"papers": papers})

from .tasks import generate_paper_task

@login_required(login_url='login')
def generate_view(request):
    patterns = ExamPattern.objects.all()

    # ✅ Unique subjects from Material table
    subjects = Material.objects.values_list("subject", flat=True).distinct()

    if request.method == "POST":
        # Get chapters as comma-separated string and split into list
        chapters_str = request.POST.get("chapters", "")
        chapters_list = [ch.strip() for ch in chapters_str.split(",") if ch.strip()]
        
        # Get blueprint ID if provided and validate it
        blueprint_id = request.POST.get("blueprint", "")
        class_name = request.POST["class_name"]
        subject = request.POST["subject"]
        
        # Handle additional documents upload
        additional_docs = request.FILES.getlist('additional_docs')
        additional_context_text = ""
        for doc_file in additional_docs:
            file_extension = os.path.splitext(doc_file.name)[1].lower()
            if file_extension == '.pdf':
                # Save PDF to a temporary file to get a path
                with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_pdf:
                    for chunk in doc_file.chunks():
                        temp_pdf.write(chunk)
                    temp_pdf_path = temp_pdf.name
                additional_context_text += extract_text_from_pdf(temp_pdf_path) + "\n"
                os.unlink(temp_pdf_path) # Clean up temp file
            elif file_extension == '.docx':
                additional_context_text += extract_text_from_docx(doc_file) + "\n"
            else:
                messages.warning(request, f"Unsupported file type uploaded: {doc_file.name}")

        # Validate blueprint if provided
        if blueprint_id:
            try:
                if blueprint_id.startswith("exam_"):
                    bp_id = blueprint_id.replace("exam_", "")
                    blueprint = ExamBlueprint.objects.get(id=bp_id, is_active=True)
                    if blueprint.class_name != class_name.split("-")[0] or blueprint.subject.lower() != subject.lower():
                        messages.error(request, "Selected blueprint doesn't match the class and subject.")
                        return render(request, "generate.html", {
                            "patterns": patterns,
                            "subjects": subjects,
                        })
                elif blueprint_id.startswith("template_"):
                    tp_id = blueprint_id.replace("template_", "")
                    template = BlueprintTemplate.objects.get(id=tp_id, is_active=True)
                    if template.class_name != class_name.split("-")[0] or template.subject.lower() != subject.lower():
                        messages.error(request, "Selected blueprint template doesn't match the class and subject.")
                        return render(request, "generate.html", {
                            "patterns": patterns,
                            "subjects": subjects,
                        })
            except (ExamBlueprint.DoesNotExist, BlueprintTemplate.DoesNotExist):
                messages.error(request, "Selected blueprint not found or is inactive.")
                return render(request, "generate.html", {
                    "patterns": patterns,
                    "subjects": subjects,
                })
        
        # Resolve selected pattern object (for test type expansion/name)
        try:
            selected_pattern = ExamPattern.objects.get(id=request.POST["pattern"])
        except ExamPattern.DoesNotExist:
            selected_pattern = None

        paper = QuestionPaper.objects.create(
            class_name=request.POST["class_name"],
            subject=request.POST["subject"],
            pattern_id=request.POST["pattern"],
            chapters=chapters_list,  # Now properly handled as list
            difficulty=request.POST["difficulty"],
            created_by=request.user if request.user.is_authenticated else None,
            status="queued"
        )
        
        # Get model choice from session, default to 'aws'
        model_source = request.session.get('model_choice', 'aws')

        # Build additional context JSON from form (duration, marks, test type) and any extracted text
        time_duration = request.POST.get("duration", "").strip()  # Fixed: form field is "duration" not "time_duration"
        total_marks = request.POST.get("total_marks", "").strip()
        meta_payload = {
            "class_name": class_name,  # Include class_name in header metadata
            "duration": time_duration,
            "marks": total_marks,
            "test_type": (selected_pattern.name if selected_pattern else ""),
            "extra_context": additional_context_text,
        }
        additional_context_json = json.dumps(meta_payload)

        # Start the task and store the task ID
        task = generate_paper_task.delay(paper.id, blueprint_id=blueprint_id, model_source=model_source, additional_context=additional_context_json)
        paper.task_id = task.id
        paper.save()
        return redirect("dashboard")

    return render(request, "generate.html", {
        "patterns": patterns,
        "subjects": subjects,
    })

# ✅ AJAX endpoint to get available subjects for a class
def get_subjects_for_class(request):
    """Get subjects that have uploaded materials for a specific class"""
    class_name = request.GET.get("class_name", "").strip()

    if not class_name:
        return JsonResponse({"subjects": []})

    # Extract just the class number (e.g., "11-A" → "11")
    class_num = class_name.split("-")[0]

    # Get distinct subjects for this class that have materials
    subjects = Material.objects.filter(
        class_name__istartswith=class_num
    ).values_list("subject", flat=True).distinct().order_by("subject")

    return JsonResponse({"subjects": list(subjects)})

# ✅ AJAX endpoint to get chapters for a subject/class
def get_chapters(request):
    class_name = request.GET.get("class_name", "").strip()
    subject = request.GET.get("subject", "").strip()

    if not class_name or not subject:
        return JsonResponse({"chapters": []})

    # Normalize for case/spacing mismatches
    chapters = Material.objects.filter(
        class_name__istartswith=class_name.split("-")[0],  # "11-A" → "11"
        subject__iexact=subject
    ).values_list("unit", flat=True).distinct()

    return JsonResponse({"chapters": list(chapters)})

# ✅ AJAX endpoint to get blueprints for a subject/class
def get_blueprints(request):
    class_name = request.GET.get("class_name", "").strip()
    subject = request.GET.get("subject", "").strip()
    
    if not class_name or not subject:
        return JsonResponse({"success": False, "error": "Class and subject are required"})
    
    try:
        # Get exam blueprints first (highest priority)
        exam_blueprints = ExamBlueprint.objects.filter(
            class_name=class_name,
            subject__iexact=subject,
            is_active=True
        ).order_by('section', 'created_at')
        
        # Get template blueprints as fallback
        template_blueprints = BlueprintTemplate.objects.filter(
            class_name=class_name,
            subject__iexact=subject,
            is_active=True
        ).order_by('is_default', 'name')
        
        blueprints = []
        
        # Add exam blueprints
        for bp in exam_blueprints:
            blueprints.append({
                "id": f"exam_{bp.id}",
                "name": f"Exam Blueprint - {bp.subject}",
                "class_name": bp.class_name,
                "subject": bp.subject,
                "section": bp.section,
                "type": "exam"
            })
        
        # Add template blueprints
        for tp in template_blueprints:
            blueprints.append({
                "id": f"template_{tp.id}",
                "name": tp.name,
                "class_name": tp.class_name,
                "subject": tp.subject,
                "section": None,
                "type": "template"
            })
        
        return JsonResponse({"success": True, "blueprints": blueprints})
        
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})

# ✅ AJAX endpoint to get pattern details
def get_pattern_details(request, pattern_id):
    """Get pattern details for AJAX display"""
    try:
        pattern = ExamPattern.objects.get(id=pattern_id)
        pattern_data = {
            "id": pattern.id,
            "name": pattern.name,
            "class_name": pattern.class_name,
            "subject": pattern.subject,
            "total_marks": pattern.total_marks,
            "total_questions": pattern.total_questions,
            "sections": pattern.sections,
            "pattern_source": pattern.pattern_source
        }
        return JsonResponse({"success": True, "pattern": pattern_data})
    except ExamPattern.DoesNotExist:
        return JsonResponse({"success": False, "error": "Pattern not found"})
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})

# ✅ AJAX endpoint to get blueprint details for preview
def get_blueprint_details(request, blueprint_id):
    try:
        if blueprint_id.startswith("exam_"):
            # Exam blueprint
            bp_id = blueprint_id.replace("exam_", "")
            blueprint = ExamBlueprint.objects.get(id=bp_id, is_active=True)
            blueprint_data = {
                "id": blueprint_id,
                "name": f"Exam Blueprint - {blueprint.subject}",
                "class_name": blueprint.class_name,
                "subject": blueprint.subject,
                "section": blueprint.section,
                "blueprint": blueprint.blueprint,
                "type": "exam"
            }
        elif blueprint_id.startswith("template_"):
            # Template blueprint
            tp_id = blueprint_id.replace("template_", "")
            template = BlueprintTemplate.objects.get(id=tp_id, is_active=True)
            blueprint_data = {
                "id": blueprint_id,
                "name": template.name,
                "class_name": template.class_name,
                "subject": template.subject,
                "section": None,
                "blueprint": template.blueprint,
                "type": "template"
            }
        else:
            return JsonResponse({"success": False, "error": "Invalid blueprint ID"})
        
        return JsonResponse({"success": True, "blueprint": blueprint_data})
        
    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)})

@login_required(login_url='login')
def patterns_view(request):
    patterns = ExamPattern.objects.all()
    return render(request, "patterns.html", {"patterns": patterns})

@login_required(login_url='login')
def pattern_detail_view(request, pattern_id):
    """Display detailed view of a pattern"""
    try:
        pattern = ExamPattern.objects.get(id=pattern_id)
        pattern_json = json.dumps(pattern.sections, indent=2)
        return render(request, "pattern_detail.html", {
            "pattern": pattern,
            "pattern_json": pattern_json
        })
    except ExamPattern.DoesNotExist:
        messages.error(request, "Pattern not found.")
        return redirect("patterns")

@login_required(login_url='login')
def pattern_edit_view(request, pattern_id):
    """Edit pattern (limited editing - only metadata, or regenerate if AI-generated)"""
    try:
        pattern = ExamPattern.objects.get(id=pattern_id)

        if request.method == "POST":
            # Check if this is a regeneration request for AI-generated patterns
            if pattern.pattern_source == 'ai_generated' and request.POST.get("action") == "regenerate":
                new_prompt = request.POST.get("ai_prompt", "").strip()

                if not new_prompt:
                    messages.error(request, "Please provide a prompt to regenerate the pattern.")
                    return render(request, "pattern_edit.html", {"pattern": pattern})

                # Regenerate pattern using new prompt
                try:
                    from .pattern_ai_generator import generate_pattern_from_text

                    pattern_data = generate_pattern_from_text(
                        teacher_input=new_prompt,
                        class_name=pattern.class_name,
                        subject=pattern.subject,
                        exam_name=pattern.name
                    )

                    # Update pattern with regenerated structure
                    pattern.sections = pattern_data['sections']
                    pattern.total_marks = pattern_data['total_marks']
                    pattern.total_questions = pattern_data['total_questions']
                    pattern.ai_prompt = new_prompt
                    pattern.save()

                    messages.success(request, f"Pattern '{pattern.name}' regenerated successfully!")
                    return redirect("pattern_detail", pattern_id=pattern.id)

                except Exception as e:
                    messages.error(request, f"Error regenerating pattern: {str(e)}")
                    return render(request, "pattern_edit.html", {"pattern": pattern})
            else:
                # Regular metadata editing
                pattern.name = request.POST.get("name", pattern.name)
                pattern.class_name = request.POST.get("class_name", pattern.class_name)
                pattern.subject = request.POST.get("subject", pattern.subject)
                pattern.description = request.POST.get("description", pattern.description)

                # Allow editing prompt for AI-generated patterns
                if pattern.pattern_source == 'ai_generated':
                    pattern.ai_prompt = request.POST.get("ai_prompt", pattern.ai_prompt)

                pattern.save()

                messages.success(request, f"Pattern '{pattern.name}' updated successfully!")
                return redirect("pattern_detail", pattern_id=pattern.id)

        return render(request, "pattern_edit.html", {"pattern": pattern})

    except ExamPattern.DoesNotExist:
        messages.error(request, "Pattern not found.")
        return redirect("patterns")

@login_required(login_url='login')
def create_pattern_view(request):
    if request.method == "POST":
        # Get form data
        class_name = request.POST.get("class_name")
        subject = request.POST.get("subject")
        pattern_name = request.POST.get("pattern_name")
        pattern_source = request.POST.get("pattern_source", "manual")  # manual or ai_generated

        # Check if this is AI pattern generation or manual
        if pattern_source == "ai_generated":
            # AI-powered pattern generation
            from .pattern_ai_generator import generate_pattern_from_text

            teacher_input = request.POST.get("teacher_input", "")
            if not teacher_input:
                messages.error(request, "Please provide pattern description for AI parsing.")
                return render(request, "create_pattern.html")

            try:
                pattern_data = generate_pattern_from_text(
                    teacher_input=teacher_input,
                    class_name=class_name,
                    subject=subject,
                    exam_name=pattern_name
                )

                # Create pattern with AI-generated structure
                pattern = ExamPattern.objects.create(
                    name=pattern_name,
                    description=f"AI-generated pattern for {class_name} {subject}",
                    subject=subject,
                    class_name=class_name,
                    sections=pattern_data['sections'],
                    total_marks=pattern_data['total_marks'],
                    total_questions=pattern_data['total_questions'],
                    pattern_source='ai_generated',
                    ai_prompt=teacher_input,
                    created_by=request.user
                )
                messages.success(request, f"AI Pattern '{pattern_name}' created successfully!")
                return redirect("patterns")

            except Exception as e:
                messages.error(request, f"Error generating pattern: {str(e)}")
                return render(request, "create_pattern.html")

        else:
            # Manual pattern creation
            # Get sections data
            sections = []
            section_count = int(request.POST.get("section_count", 0))

            for i in range(section_count):
                section_name = request.POST.get(f"section_{i}_name", "")
                section_questions = request.POST.get(f"section_{i}_questions")
                section_marks = request.POST.get(f"section_{i}_marks")
                section_types = request.POST.getlist(f"section_{i}_types")  # Multiple question types
                section_instructions = request.POST.get(f"section_{i}_instructions", "")

                if section_questions and section_marks:
                    # Use provided name or default letter
                    section_letter = section_name or chr(65 + i)  # 65 is ASCII for 'A'

                    section_obj = {
                        "id": section_letter,
                        "name": section_name or f"Section {section_letter}",
                        "marks": int(section_marks),
                        "questions_count": int(section_questions),
                        "marks_per_question": 1,  # Will be calculated
                        "question_types": section_types if section_types else ["Short Answer"],
                        "instructions": [section_instructions] if section_instructions else [],
                        "constraints": {},
                        "subsections": []
                    }

                    # Calculate marks per question
                    if int(section_questions) > 0:
                        section_obj["marks_per_question"] = int(section_marks) / int(section_questions)

                    sections.append(section_obj)

            # Create the pattern with unified structure
            if pattern_name and sections:
                # Calculate totals
                total_marks = sum(s['marks'] for s in sections)
                total_questions = sum(s['questions_count'] for s in sections)

                pattern = ExamPattern.objects.create(
                    name=pattern_name,
                    description=f"Manual pattern for {class_name} {subject}",
                    subject=subject,
                    class_name=class_name,
                    sections=sections,
                    total_marks=total_marks,
                    total_questions=total_questions,
                    pattern_source='manual',
                    created_by=request.user
                )
                messages.success(request, f"Pattern '{pattern_name}' created successfully!")
                return redirect("patterns")
            else:
                messages.error(request, "Please fill in all required fields.")

    return render(request, "create_pattern.html")

@login_required(login_url='login')
def delete_pattern_view(request, pattern_id):
    try:
        pattern = ExamPattern.objects.get(id=pattern_id)
        pattern_name = pattern.name
        pattern.delete()
        messages.success(request, f"Pattern '{pattern_name}' deleted successfully!")
    except ExamPattern.DoesNotExist:
        messages.error(request, "Pattern not found.")
    
    return redirect("patterns")

@login_required(login_url='login')
def upload_material(request):
    if request.method == "POST":
        class_name = request.POST["class_name"]
        subject = request.POST["subject"]
        material_type = request.POST["type"]
        bulk_upload = request.POST.get("bulk_upload") == "on"
        
        materials_to_ingest = []

        # Handle bulk upload
        if bulk_upload:
            import os
            files = request.FILES.getlist("bulk_files")
            
            for file in files:
                if not file:
                    continue
                
                # Get filename without extension
                filename = file.name
                # Remove .pdf, .PDF, or any extension
                base_name = os.path.splitext(filename)[0]
                
                # Use filename as both title and unit name
                unit = base_name
                title = base_name
                
                material = Material.objects.create(
                    class_name=class_name,
                    subject=subject,
                    unit=unit if material_type == 'textbook' else None,
                    title=title,
                    type=material_type,
                    file=file,
                    uploaded_by=request.user if request.user.is_authenticated else None,
                )
                materials_to_ingest.append({
                    "unit": unit if material_type == 'textbook' else None,
                    "title": title,
                    "file_path": material.file.path,
                })
        
        elif material_type == 'textbook':
            chapter_count = int(request.POST.get("chapter_count", 1))
            for i in range(chapter_count):
                unit = request.POST.get(f"unit_{i}")
                title = request.POST.get(f"title_{i}")
                file = request.FILES.get(f"file_{i}")

                if not file:
                    continue

                material = Material.objects.create(
                    class_name=class_name,
                    subject=subject,
                    unit=unit,
                    title=title,
                    type=material_type,
                    file=file,
                    uploaded_by=request.user if request.user.is_authenticated else None,
                )
                materials_to_ingest.append({
                    "unit": unit,
                    "title": title,
                    "file_path": material.file.path,
                })
        else:
            material_count = int(request.POST.get("material_count", 1))
            for i in range(material_count):
                title = request.POST.get(f"title_{i}")
                file = request.FILES.get(f"file_{i}")

                if not file:
                    continue

                material = Material.objects.create(
                    class_name=class_name,
                    subject=subject,
                    unit=None,  # No unit for these types
                    title=title,
                    type=material_type,
                    file=file,
                    uploaded_by=request.user if request.user.is_authenticated else None,
                )
                materials_to_ingest.append({
                    "unit": None,
                    "title": title,
                    "file_path": material.file.path,
                })

        if materials_to_ingest:
            try:
                # Print which PDFs are being processed
                print(f"[Embeddings] Starting bulk ingestion for {class_name} {subject}")
                print(f"[Embeddings] Processing {len(materials_to_ingest)} file(s):")
                for i, mat in enumerate(materials_to_ingest, 1):
                    pdf_name = os.path.basename(mat.get("file_path", "unknown"))
                    print(f"  {i}. {pdf_name} (Unit: {mat.get('unit', 'N/A')}, Title: {mat.get('title', 'N/A')})")
                
                chunks_added = embeddings.ingest_bulk(class_name, subject, materials_to_ingest)
                print(f"[Embeddings] Successfully stored {chunks_added} chunks for {class_name} {subject}")
                # Avoid using session-backed messages to prevent SessionInterrupted on long requests
                print(f"[Upload] SUCCESS: Uploaded {len(materials_to_ingest)} materials and generated embeddings.")
            except Exception as e:
                import traceback
                error_msg = str(e)
                print(f"[Embeddings ERROR] Bulk ingestion failed for {class_name} {subject}")
                print(f"[Embeddings ERROR] Error: {error_msg}")
                print(f"[Embeddings ERROR] Traceback: {traceback.format_exc()}")
                
                # Extract PDF filename from error if available
                pdf_name = "unknown PDF"
                if "PDF '" in error_msg:
                    try:
                        pdf_name = error_msg.split("PDF '")[1].split("'")[0]
                    except:
                        pass
                elif "pdf:" in error_msg.lower():
                    try:
                        pdf_name = error_msg.split("pdf:")[1].split("|")[0].strip()
                    except:
                        pass
                
                # Provide more helpful error message
                if "invalid literal for int" in error_msg or "base 16" in error_msg:
                    if "pdf" in error_msg.lower() or "page" in error_msg.lower() or "extract_text" in error_msg.lower():
                        print(f"[Upload WARN] Some pages in PDF(s) could not be parsed (malformed content). PDF: {pdf_name}. Processed pages were uploaded successfully.")
                    else:
                        print("[Upload WARN] The embedding database was corrupted and has been reset. Please try uploading again.")
                elif "chromadb" in error_msg.lower() or "collection" in error_msg.lower():
                    print(f"[Upload ERROR] Database error during embedding. PDF: {pdf_name}. Error: {error_msg[:100]}")
                elif "no text could be extracted" in error_msg.lower():
                    print(f"[Upload ERROR] Could not extract any text from PDF: {pdf_name}. The file may be corrupted or image-only.")
                elif "cannot read pdf" in error_msg.lower() or "failed to open pdf" in error_msg.lower():
                    print(f"[Upload ERROR] Cannot read PDF file: {pdf_name}. The file may be corrupted or in an unsupported format.")
                else:
                    print(f"[Upload ERROR] Error processing PDF: {pdf_name}. {error_msg[:150]}")
        else:
            # Avoid session-backed messages
            print("[Upload WARN] No files were uploaded.")

        return redirect("dashboard")

    return render(request, "upload.html")

@login_required(login_url='login')
def materials_list_view(request):
    """View to list all materials grouped by class and subject"""
    # Get filter parameters
    class_filter = request.GET.get('class', '')
    subject_filter = request.GET.get('subject', '')
    
    # Get all materials
    materials = Material.objects.all().order_by('class_name', 'subject', 'unit', 'title')
    
    # Apply filters
    if class_filter:
        materials = materials.filter(class_name__icontains=class_filter)
    if subject_filter:
        materials = materials.filter(subject__icontains=subject_filter)
    
    # Group materials by class and subject
    grouped_materials = {}
    for material in materials:
        key = f"{material.class_name}_{material.subject}"
        if key not in grouped_materials:
            grouped_materials[key] = {
                'class_name': material.class_name,
                'subject': material.subject,
                'materials': []
            }
        grouped_materials[key]['materials'].append(material)
    
    # Get unique classes and subjects for filter dropdowns
    classes = sorted(set(Material.objects.values_list('class_name', flat=True).distinct()))
    subjects = sorted(set(Material.objects.values_list('subject', flat=True).distinct()))
    
    context = {
        'grouped_materials': grouped_materials,
        'classes': classes,
        'subjects': subjects,
        'class_filter': class_filter,
        'subject_filter': subject_filter,
    }
    
    return render(request, "materials_list.html", context)

@login_required(login_url='login')
def edit_material_view(request, material_id):
    """Edit material (unit/title)"""
    try:
        material = Material.objects.get(id=material_id)
    except Material.DoesNotExist:
        messages.error(request, "Material not found.")
        return redirect("materials_list")
    
    if request.method == "POST":
        unit = request.POST.get("unit", "").strip()
        title = request.POST.get("title", "").strip()
        
        if not title:
            messages.error(request, "Title is required.")
            return render(request, "edit_material.html", {"material": material})
        
        material.unit = unit if unit else None
        material.title = title
        material.save()
        
        messages.success(request, f"Material '{material.title}' updated successfully.")
        return redirect("materials_list")
    
    return render(request, "edit_material.html", {"material": material})

@login_required(login_url='login')
def delete_material_view(request, material_id):
    """Delete material"""
    try:
        material = Material.objects.get(id=material_id)
        title = material.title
        material.delete()
        messages.success(request, f"Material '{title}' deleted successfully.")
    except Material.DoesNotExist:
        messages.error(request, "Material not found.")
    
    return redirect("materials_list")

@login_required(login_url='login')
def bulk_delete_materials_view(request):
    """Bulk delete materials"""
    if request.method == "POST":
        material_ids = request.POST.getlist("material_ids")
        
        if not material_ids:
            messages.warning(request, "No materials selected for deletion.")
            return redirect("materials_list")
        
        try:
            materials = Material.objects.filter(id__in=material_ids)
            count = materials.count()
            materials.delete()
            messages.success(request, f"Successfully deleted {count} material(s).")
        except Exception as e:
            messages.error(request, f"Error deleting materials: {str(e)}")
    
    return redirect("materials_list")

# Authentication Views
def login_view(request):
    # Always show login page - no automatic redirects for authenticated users
    # This ensures root URL always goes to login page
    
    if request.method == "POST":
        # Handle login form submission
        username = request.POST.get("username")
        password = request.POST.get("password")
        
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, f"Welcome back, {user.username}!")
            # First-login password change prompt for non-admins
            try:
                needs_change = (not user.is_superuser) and user.profile.require_password_change
            except Exception:
                needs_change = False
            if needs_change:
                return redirect('password_change_prompt')

            # Redirect to next page if specified, otherwise go to dashboard
            next_page = request.GET.get('next', 'dashboard')
            print(f"[DEBUG] Redirecting to: {next_page}")
            return redirect(next_page)
        else:
            messages.error(request, "Invalid username or password.")
    
    return render(request, "login.html")

def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out successfully.")
    return redirect("login")

def clear_session_view(request):
    """Clear all session data and redirect to login"""
    request.session.flush()
    messages.info(request, "Session cleared. Please log in again.")
    return redirect("login")

def register_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        email = request.POST.get("email")
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")
        
        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, "register.html")
        
        if len(password) < 8:
            messages.error(request, "Password must be at least 8 characters long.")
            return render(request, "register.html")
        
        from django.contrib.auth.models import User
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return render(request, "register.html")
        
        if User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists.")
            return render(request, "register.html")
        
        user = User.objects.create_user(username=username, email=email, password=password)
        messages.success(request, "Account created successfully! Please log in.")
        return redirect("login")


# =========================
# Admin: Create new users
# =========================
@login_required(login_url='login')
def admin_create_user_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "You are not authorized to access this page.")
        return redirect('dashboard')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        is_staff = request.POST.get('is_staff') == 'on'

        if not username or not password:
            messages.error(request, 'Username and password are required.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')
        else:
            user = User.objects.create_user(username=username, password=password)
            user.is_staff = is_staff
            user.save()
            # Ensure profile exists; default require_password_change=True via signal
            messages.success(request, f"User '{username}' created successfully.")
            return redirect('admin_create_user')
    users = User.objects.all().order_by('-date_joined')

    # Fetch all question papers, order by class_name, subject, created_at
    papers = QuestionPaper.objects.all().order_by('class_name', 'subject', '-created_at')

    # Group by class and subject
    from collections import defaultdict
    paper_groups = defaultdict(lambda: defaultdict(list))
    for paper in papers:
        paper_groups[paper.class_name][paper.subject].append(paper)

    # Sort groups (class, subject)
    grouped_list = []
    for class_name in sorted(paper_groups.keys()):
        subj_group = []
        for subject in sorted(paper_groups[class_name].keys()):
            subj_group.append({
                'subject': subject,
                'papers': paper_groups[class_name][subject]
            })
        grouped_list.append({
            'class_name': class_name,
            'subjects': subj_group
        })

    return render(request, 'admin_create_user.html', {
        'users': users,
        'papers_by_class': grouped_list
    })


# =========================
# Password change prompt
# =========================
@login_required(login_url='login')
def password_change_prompt_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'skip':
            # Skip and proceed; turn off the flag
            try:
                request.user.profile.require_password_change = False
                request.user.profile.save()
            except Exception:
                pass
            return redirect('dashboard')
        return redirect('password_change_form')
    return render(request, 'password_change_prompt.html')


@login_required(login_url='login')
def password_change_form_view(request):
    if request.method == 'POST':
        pwd1 = request.POST.get('password')
        pwd2 = request.POST.get('confirm_password')

        if not pwd1 or not pwd2:
            messages.error(request, 'Please enter your new password twice.')
        elif pwd1 != pwd2:
            messages.error(request, 'Passwords do not match.')
        elif len(pwd1) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
        else:
            # Update the password
            request.user.set_password(pwd1)
            request.user.save()

            # Optional: disable the "require password change" flag
            try:
                request.user.profile.require_password_change = False
                request.user.profile.save()
            except Exception:
                pass

            messages.success(request, 'Password updated. Please log in again.')
            return redirect('login')

    # Render the password change form if GET request or validation failed
    return render(request, 'password_change_form.html')


@login_required(login_url='login')
def admin_delete_user_view(request, user_id):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "You are not authorized to perform this action.")
        return redirect('dashboard')
    if request.method != 'POST':
        return redirect('admin_create_user')
    try:
        user = User.objects.get(id=user_id)
        if user == request.user:
            messages.error(request, "You cannot delete your own account.")
        elif user.is_superuser:
            messages.error(request, "Cannot delete a superuser from this page.")
        else:
            username = user.username
            user.delete()
            messages.success(request, f"User '{username}' deleted.")
    except User.DoesNotExist:
        messages.error(request, "User not found.")
    return redirect('admin_create_user')

@login_required(login_url='login')
def update_model_choice(request):
    if request.method == 'POST':
        model_choice = request.POST.get('model_choice')
        if model_choice == 'aws':
            request.session['model_choice'] = 'aws'
            messages.success(request, "Switched to AWS models.")
        else:
            request.session['model_choice'] = 'local'
            messages.success(request, "Switched to local Ollama models.")
    return redirect('dashboard')

@login_required(login_url='login')
def retry_paper_view(request, paper_id):
    try:
        paper = QuestionPaper.objects.get(id=paper_id)
        if paper.status == "failed":
            # Reset status and retry
            paper.status = "queued"
            paper.save()
            # Start new task and store task ID
            task = generate_paper_task.delay(paper.id)
            paper.task_id = task.id
            paper.save()
            messages.success(request, f"Question paper for {paper.class_name} {paper.subject} has been queued for retry.")
        else:
            messages.warning(request, "Only failed papers can be retried.")
    except QuestionPaper.DoesNotExist:
        messages.error(request, "Question paper not found.")
    
    return redirect("dashboard")

@login_required(login_url='login')
def delete_paper_view(request, paper_id):
    try:
        paper = QuestionPaper.objects.get(id=paper_id)
        
        # If paper is generating, try to revoke the Celery task
        if paper.status == "generating" and paper.task_id:
            try:
                from celery import current_app
                # Revoke the task with terminate=True to forcefully stop it
                current_app.control.revoke(paper.task_id, terminate=True, signal='SIGKILL')
                print(f"[Delete] Successfully revoked task {paper.task_id}")
                messages.success(request, f"Generation cancelled and paper deleted for {paper.class_name} {paper.subject}.")
            except Exception as e:
                print(f"[Delete Error] Could not cancel task {paper.task_id}: {e}")
                messages.warning(request, f"Paper deleted but task cancellation failed: {paper.class_name} {paper.subject}.")
        elif paper.status == "generating" and not paper.task_id:
            # Paper is generating but no task ID stored, just mark as cancelled
            paper.status = "cancelled"
            paper.save()
            messages.success(request, f"Generation marked as cancelled and paper deleted for {paper.class_name} {paper.subject}.")
        else:
            messages.success(request, f"Question paper deleted for {paper.class_name} {paper.subject}.")
        
        # Delete the file if it exists
        if paper.file:
            try:
                paper.file.delete(save=False)
            except Exception as e:
                print(f"[Delete Error] Could not delete file: {e}")
        
        # Delete the paper record
        paper.delete()
        
    except QuestionPaper.DoesNotExist:
        messages.error(request, "Question paper not found.")
    except Exception as e:
        messages.error(request, f"Error deleting paper: {str(e)}")
    
    return redirect("dashboard")

# ================================
# Blueprint Management Views
# ================================

@login_required(login_url='login')
def blueprint_list_view(request):
    """List all blueprint templates and exam blueprints"""
    templates = BlueprintTemplate.objects.filter(is_active=True).order_by('subject', 'class_name')
    blueprints = ExamBlueprint.objects.filter(is_active=True).order_by('class_name', 'subject')
    
    return render(request, "blueprint_list.html", {
        "templates": templates,
        "blueprints": blueprints
    })

@login_required(login_url='login')
def blueprint_template_create_view(request):
    """Create a new blueprint template"""
    if request.method == "POST":
        try:
            name = request.POST.get("name")
            subject = request.POST.get("subject")
            class_name = request.POST.get("class_name")
            description = request.POST.get("description", "")
            is_default = request.POST.get("is_default") == "on"
            
            # Get blueprint data from dynamic form
            blueprint_json = request.POST.get("blueprint", "").strip()
            if blueprint_json:
                # Validate JSON
                try:
                    blueprint_data = json.loads(blueprint_json)
                except json.JSONDecodeError as e:
                    messages.error(request, f"Invalid blueprint data: {str(e)}")
                    return render(request, "blueprint_template_create_dynamic.html")
            else:
                messages.error(request, "Blueprint data is required.")
                return render(request, "blueprint_template_create_dynamic.html")
            
            if name and subject and class_name and blueprint_data:
                # If this is set as default, unset other defaults for this subject/class
                if is_default:
                    BlueprintTemplate.objects.filter(
                        subject=subject, 
                        class_name=class_name, 
                        is_default=True
                    ).update(is_default=False)
                
                template = BlueprintTemplate.objects.create(
                    name=name,
                    subject=subject,
                    class_name=class_name,
                    description=description,
                    blueprint=blueprint_data,
                    is_default=is_default,
                    created_by=request.user
                )
                messages.success(request, f"Blueprint template '{name}' created successfully!")
                return redirect("blueprint_list")
            else:
                messages.error(request, "Please fill in all required fields.")
                
        except Exception as e:
            messages.error(request, f"Error creating template: {str(e)}")
    
    return render(request, "blueprint_template_create_dynamic.html")

@login_required(login_url='login')
def blueprint_template_edit_view(request, template_id):
    """Edit an existing blueprint template"""
    template = get_object_or_404(BlueprintTemplate, id=template_id)
    
    if request.method == "POST":
        try:
            # Update basic template info
            template.name = request.POST.get("name")
            template.class_name = request.POST.get("class_name")
            template.subject = request.POST.get("subject")
            template.description = request.POST.get("description", "")
            template.is_default = request.POST.get("is_default") == "on"
            
            # Handle blueprint JSON
            blueprint_json = request.POST.get("blueprint", "").strip()
            if blueprint_json:
                # Validate JSON
                try:
                    blueprint_data = json.loads(blueprint_json)
                    template.blueprint = blueprint_data
                except json.JSONDecodeError as e:
                    messages.error(request, f"Invalid JSON format: {str(e)}")
                    return render(request, "blueprint_template_edit_simple.html", {"template": template})
            else:
                messages.error(request, "Blueprint JSON is required.")
                return render(request, "blueprint_template_edit_simple.html", {"template": template})
            
            # If this is set as default, unset other defaults for this subject/class
            if template.is_default:
                BlueprintTemplate.objects.filter(
                    subject=template.subject, 
                    class_name=template.class_name, 
                    is_default=True
                ).exclude(id=template.id).update(is_default=False)
            
            template.save()
            messages.success(request, f"Template '{template.name}' updated successfully!")
            return redirect("blueprint_list")
            
        except Exception as e:
            messages.error(request, f"Error updating template: {str(e)}")
            return render(request, "blueprint_template_edit_dynamic.html", {"template": template})
    
    return render(request, "blueprint_template_edit_dynamic.html", {"template": template})

@login_required(login_url='login')
def blueprint_template_delete_view(request, template_id):
    """Delete a blueprint template"""
    template = get_object_or_404(BlueprintTemplate, id=template_id)
    template_name = template.name
    template.delete()
    messages.success(request, f"Blueprint template '{template_name}' deleted successfully!")
    return redirect("blueprint_list")

@login_required(login_url='login')
def exam_blueprint_create_view(request):
    """Create a new exam blueprint from template"""
    templates = BlueprintTemplate.objects.filter(is_active=True).order_by('subject', 'class_name')
    
    if request.method == "POST":
        class_name = request.POST.get("class_name")
        subject = request.POST.get("subject")
        section = request.POST.get("section", "")
        code = request.POST.get("code", "")
        template_id = request.POST.get("template")
        
        if class_name and subject and template_id:
            template = get_object_or_404(BlueprintTemplate, id=template_id)
            
            blueprint = ExamBlueprint.objects.create(
                class_name=class_name,
                subject=subject,
                section=section if section else None,
                code=code if code else None,
                blueprint=template.blueprint,
                template=template,
                created_by=request.user
            )
            messages.success(request, f"Exam blueprint for {class_name} {subject} created successfully!")
            return redirect("blueprint_list")
        else:
            messages.error(request, "Please fill in all required fields.")
    
    return render(request, "exam_blueprint_create.html", {"templates": templates})

@login_required(login_url='login')
def exam_blueprint_edit_view(request, blueprint_id):
    """Edit an existing exam blueprint"""
    blueprint = get_object_or_404(ExamBlueprint, id=blueprint_id)
    
    if request.method == "POST":
        blueprint.class_name = request.POST.get("class_name")
        blueprint.subject = request.POST.get("subject")
        blueprint.section = request.POST.get("section", "")
        blueprint.code = request.POST.get("code", "")
        
        # Get sections data
        sections = []
        section_count = int(request.POST.get("section_count", 0))
        
        for i in range(section_count):
            section_name = request.POST.get(f"section_{i}_name")
            section_title = request.POST.get(f"section_{i}_title")
            section_marks = request.POST.get(f"section_{i}_marks")
            question_types = request.POST.get(f"section_{i}_question_types", "")
            
            if section_name and section_title and section_marks:
                sections.append({
                    "name": section_name,
                    "title": section_title,
                    "marks": int(section_marks),
                    "question_types": [qt.strip() for qt in question_types.split(",") if qt.strip()]
                })
        
        if blueprint.class_name and blueprint.subject and sections:
            blueprint.blueprint = {"sections": sections}
            blueprint.save()
            messages.success(request, f"Exam blueprint for {blueprint.class_name} {blueprint.subject} updated successfully!")
            return redirect("blueprint_list")
        else:
            messages.error(request, "Please fill in all required fields.")
    
    return render(request, "exam_blueprint_edit.html", {"blueprint": blueprint})

@login_required(login_url='login')
def exam_blueprint_delete_view(request, blueprint_id):
    """Delete an exam blueprint"""
    blueprint = get_object_or_404(ExamBlueprint, id=blueprint_id)
    blueprint_name = f"{blueprint.class_name} {blueprint.subject}"
    blueprint.delete()
    messages.success(request, f"Exam blueprint for '{blueprint_name}' deleted successfully!")
    return redirect("blueprint_list")

@login_required(login_url='login')
def bulk_delete_papers_view(request):
    """Delete multiple question papers at once"""
    if request.method == "POST":
        paper_ids = request.POST.getlist('paper_ids')
        
        if not paper_ids:
            messages.warning(request, "No papers selected for deletion.")
            return redirect("dashboard")
        
        deleted_count = 0
        cancelled_count = 0
        error_count = 0
        
        for paper_id in paper_ids:
            try:
                paper = QuestionPaper.objects.get(id=paper_id)
                
                # If paper is generating, try to revoke the Celery task
                if paper.status == "generating" and paper.task_id:
                    try:
                        from celery import current_app
                        # Revoke the task with terminate=True to forcefully stop it
                        current_app.control.revoke(paper.task_id, terminate=True, signal='SIGKILL')
                        cancelled_count += 1
                    except Exception as e:
                        print(f"[Bulk Delete Error] Could not cancel task {paper.task_id}: {e}")
                        error_count += 1
                elif paper.status == "generating" and not paper.task_id:
                    # Paper is generating but no task ID stored, just mark as cancelled
                    paper.status = "cancelled"
                    paper.save()
                    cancelled_count += 1
                else:
                    deleted_count += 1
                
                # Delete the file if it exists
                if paper.file:
                    try:
                        paper.file.delete(save=False)
                    except Exception as e:
                        print(f"[Bulk Delete Error] Could not delete file: {e}")
                
                # Delete the paper record
                paper.delete()
                
            except QuestionPaper.DoesNotExist:
                error_count += 1
            except Exception as e:
                print(f"[Bulk Delete Error] {e}")
                error_count += 1
        
        # Show appropriate success message
        if deleted_count > 0 and cancelled_count > 0:
            messages.success(request, f"Successfully deleted {deleted_count} papers and cancelled {cancelled_count} generating papers.")
        elif deleted_count > 0:
            messages.success(request, f"Successfully deleted {deleted_count} question papers.")
        elif cancelled_count > 0:
            messages.success(request, f"Successfully cancelled {cancelled_count} generating papers.")
        
        if error_count > 0:
            messages.warning(request, f"Failed to delete {error_count} papers. Please try again.")

    return redirect("dashboard")


# ✅ Edit paper view - Display editing interface
@login_required(login_url='login')
def edit_paper(request, paper_id):
    """Display the paper editing interface"""
    paper = get_object_or_404(QuestionPaper, id=paper_id)

    # Extract content from PDF file
    content = extract_text_from_pdf(paper.file.path) if paper.file else "No content available"

    return render(request, "edit_paper.html", {
        "paper": paper,
        "content": content
    })


# ✅ Save paper edits - AJAX endpoint
@login_required(login_url='login')
def save_paper_edits(request, paper_id):
    """Save edited content"""
    paper = get_object_or_404(QuestionPaper, id=paper_id)

    if request.method == "POST":
        try:
            data = json.loads(request.body)
            content = data.get("content", "")

            # Store edited content in a text field (add this to model if needed)
            paper.edited_content = content
            paper.save()

            return JsonResponse({"success": True, "message": "Changes saved successfully"})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request method"})


#✅Generate PDF from edited content
@login_required(login_url='login')
def generate_paper_pdf(request, paper_id):
    """Generate PDF from edited content"""
    paper = get_object_or_404(QuestionPaper, id=paper_id)

    if request.method == "POST":
        try:
            data = json.loads(request.body)
            content = data.get("content", "")

            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.utils import simpleSplit
            from io import BytesIO
            from PyPDF2 import PdfWriter
            import os

            # Create PDF from content
            packet = BytesIO()
            can = canvas.Canvas(packet, pagesize=A4)
            y = 750

            can.setFont("Helvetica", 11)
            lines = content.split('\n')

            for line in lines:
                if y < 50:
                    can.showPage()
                    y = 750
                    can.setFont("Helvetica", 11)

                if line.strip():
                    wrapped_lines = simpleSplit(line, "Helvetica", 11, 500)
                    for wrapped_line in wrapped_lines:
                        if y < 50:
                            can.showPage()
                            y = 750
                        can.drawString(50, y, wrapped_line)
                        y -= 14
                else:
                    y -= 10

            can.save()
            packet.seek(0)

            # Save the PDF
            from django.conf import settings
            output_dir = os.path.join(settings.MEDIA_ROOT, "question_papers")
            os.makedirs(output_dir, exist_ok=True)

            filename = f"edited_{paper.subject}_{paper.id}.pdf"
            filepath = os.path.join(output_dir, filename)

            with open(filepath, 'wb') as f:
                f.write(packet.getvalue())

            # Update the paper file
            from django.core.files import File
            paper.file.save(filename, File(open(filepath, 'rb')))
            paper.save()

            return JsonResponse({"success": True, "message": "PDF generated successfully"})
        except Exception as e:
            import traceback
            return JsonResponse({"success": False, "error": str(e), "traceback": traceback.format_exc()})

    return JsonResponse({"success": False, "error": "Invalid request method"})


def extract_text_from_pdf(pdf_path):
    """Extract text content from PDF file"""
    import os
    
    # Check if file exists
    if not os.path.exists(pdf_path):
        return f"PDF file not found: {pdf_path}"
    
    # Try PyPDF2 first
    try:
        import PyPDF2
        from PyPDF2.errors import PdfReadError
        
        with open(pdf_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                try:
                    page_text = page.extract_text() or ""
                    text += page_text + "\n"
                except Exception as page_error:
                    # Skip problematic pages but continue
                    print(f"[PDF Extract] Warning: Skipping page due to error: {str(page_error)[:80]}")
                    continue
            if text.strip():
                return text[:5000]  # Limit to first 5000 chars for editing
    except PdfReadError as e:
        error_msg = str(e)
        # Check for specific EOF error
        if "EOF marker not found" in error_msg or "EOF" in error_msg:
            print(f"[PDF Extract] PyPDF2 EOF error, trying pdfplumber fallback...")
        else:
            print(f"[PDF Extract] PyPDF2 error: {error_msg[:100]}, trying pdfplumber fallback...")
    except Exception as e:
        error_msg = str(e)
        print(f"[PDF Extract] PyPDF2 error: {error_msg[:100]}, trying pdfplumber fallback...")
    
    # Fallback to pdfplumber if PyPDF2 fails
    try:
        import pdfplumber
        text = ""
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                try:
                    page_text = page.extract_text() or ""
                    if page_text:
                        text += page_text + "\n"
                except Exception as page_error:
                    print(f"[PDF Extract] Warning: Skipping page {page.page_number} due to error: {str(page_error)[:80]}")
                    continue
        if text.strip():
            return text[:5000]  # Limit to first 5000 chars for editing
        else:
            return "Could not extract text from PDF (file may be image-based or corrupted)"
    except ImportError:
        return "Could not extract PDF content: pdfplumber not installed. Please install it with: pip install pdfplumber"
    except Exception as e:
        return f"Could not extract PDF content: {str(e)}"
    
    return "Could not extract any text from PDF file"

# Helper function to extract text from DOCX files
def extract_text_from_docx(docx_file):
    """Extract text content from DOCX file"""
    try:
        document = docx.Document(docx_file)
        text = []
        for paragraph in document.paragraphs:
            text.append(paragraph.text)
        return "\n".join(text)
    except Exception as e:
        return f"Could not extract DOCX content: {str(e)}"

