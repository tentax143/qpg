from django.shortcuts import render, redirect, get_object_or_404
from .models import QuestionPaper, ExamPattern, Material, BlueprintTemplate, ExamBlueprint
from . import embeddings
from django.http import JsonResponse
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import json


@login_required(login_url='login')
def dashboard_view(request):
    papers = QuestionPaper.objects.all().order_by("-created_at")[:10]
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
        
        paper = QuestionPaper.objects.create(
            class_name=request.POST["class_name"],
            subject=request.POST["subject"],
            pattern_id=request.POST["pattern"],
            chapters=chapters_list,  # Now properly handled as list
            difficulty=request.POST["difficulty"],
            created_by=request.user if request.user.is_authenticated else None,
            status="queued"
        )
        
        # Start the task and store the task ID
        task = generate_paper_task.delay(paper.id, blueprint_id=blueprint_id)
        paper.task_id = task.id
        paper.save()
        return redirect("dashboard")

    return render(request, "generate.html", {
        "patterns": patterns,
        "subjects": subjects,
    })

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
def create_pattern_view(request):
    if request.method == "POST":
        # Get form data
        class_name = request.POST.get("class_name")
        subject = request.POST.get("subject")
        pattern_name = request.POST.get("pattern_name")
        
        # Get sections data
        sections = []
        section_count = int(request.POST.get("section_count", 0))
        
        # Debug: Print all POST data
        print(f"[DEBUG] Section count: {section_count}")
        print(f"[DEBUG] All POST data: {dict(request.POST)}")
        
        for i in range(section_count):
            section_questions = request.POST.get(f"section_{i}_questions")
            section_marks = request.POST.get(f"section_{i}_marks")
            
            print(f"[DEBUG] Section {i}: questions={section_questions}, marks={section_marks}")
            
            if section_questions and section_marks:
                # Use letters A, B, C, etc. for section names
                section_letter = chr(65 + i)  # 65 is ASCII for 'A'
                sections.append({
                    "name": section_letter,
                    "questions": int(section_questions),
                    "marks": int(section_marks)
                })
        
        print(f"[DEBUG] Final sections: {sections}")
        
        # Create the pattern with the specific format
        if pattern_name and sections:
            pattern_data = {"Sections": sections}
            pattern = ExamPattern.objects.create(
                name=pattern_name,
                description=f"Pattern for {class_name} {subject}",
                sections=pattern_data,
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
        chapter_count = int(request.POST.get("chapter_count", 1))

        chapters = []
        for i in range(chapter_count):
            unit = request.POST.get(f"unit_{i}")
            title = request.POST.get(f"title_{i}")
            file = request.FILES.get(f"file_{i}")

            if not file:
                continue

            # Save each Material object to DB
            material = Material.objects.create(
                class_name=class_name,
                subject=subject,
                unit=unit,
                title=title,
                type=material_type,
                file=file,
                uploaded_by=request.user if request.user.is_authenticated else None,
            )

            chapters.append({
                "unit": unit,
                "title": title,
                "file_path": material.file.path,
            })

        # ✅ Call bulk embeddings ingestion
        try:
            chunks_added = embeddings.ingest_bulk(class_name, subject, chapters)
            print(f"[Embeddings] Stored {chunks_added} chunks for {class_name} {subject}")
        except Exception as e:
            print(f"[Embeddings ERROR] {e}")

        return redirect("dashboard")

    return render(request, "upload.html")

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
    
    return render(request, "register.html")

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

