from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import QuestionPaper
from .forms import GeneratePaperForm
from .llm_backend.generator import generate_paper

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            login(request, user)
            next_url = request.GET.get('next', 'dashboard')
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
    
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    messages.success(request, 'You have been successfully logged out.')
    return redirect('login')

@login_required
def dashboard_view(request):
    papers = QuestionPaper.objects.filter(teacher=request.user).order_by("-created_at")
    return render(request, "dashboard.html", {"papers": papers})

@login_required
def generate_view(request):
    if request.method == "POST":
        form = GeneratePaperForm(request.POST)
        if form.is_valid():
            class_name = form.cleaned_data["class_name"]
            subject = form.cleaned_data["subject"]
            unit = form.cleaned_data["unit"]
            difficulty = form.cleaned_data["difficulty"]

            try:
                # Call LLM backend - now returns (file_path, summary)
                pdf_path, summary = generate_paper(class_name, subject, unit, difficulty)

                # Save in DB
                qp = QuestionPaper.objects.create(
                    teacher=request.user,
                    class_name=class_name,
                    subject=subject,
                    unit=unit,
                    difficulty=difficulty,
                    pdf_file=pdf_path,
                    status="generated",  # Set status explicitly
                )
                
                messages.success(request, f"Question paper generated successfully! {subject} paper for Class {class_name}, Unit {unit} ({difficulty} difficulty) has been created.")
                return redirect("dashboard")
                
            except ValueError as e:
                # Handle configuration errors (e.g., no exam pattern found)
                messages.error(request, f"Configuration error: {str(e)}")
            except Exception as e:
                # Handle other errors (e.g., Bedrock API issues, PDF generation)
                messages.error(request, f"Error generating question paper: {str(e)}")
                print(f"Error in generate_paper: {e}")
    else:
        form = GeneratePaperForm()

    return render(request, "generate.html", {"form": form})

@login_required
def exam_pattern_view(request):
    """View for Exam Pattern and Portion page"""
    
    # Sample exam pattern data - you can make this dynamic based on class/subject
    exam_patterns = {
        "Class 8": {
            "total_marks": 100,
            "duration": "3 hours",
            "sections": [
                {"name": "Section A", "marks": 40, "type": "Objective Type (MCQs)"},
                {"name": "Section B", "marks": 30, "type": "Short Answer Questions"},
                {"name": "Section C", "marks": 30, "type": "Long Answer Questions"},
            ]
        },
        "Class 9": {
            "total_marks": 100,
            "duration": "3 hours",
            "sections": [
                {"name": "Section A", "marks": 35, "type": "Objective Type (MCQs)"},
                {"name": "Section B", "marks": 35, "type": "Short Answer Questions"},
                {"name": "Section C", "marks": 30, "type": "Long Answer Questions"},
            ]
        },
        "Class 10": {
            "total_marks": 100,
            "duration": "3 hours",
            "sections": [
                {"name": "Section A", "marks": 30, "type": "Objective Type (MCQs)"},
                {"name": "Section B", "marks": 40, "type": "Short Answer Questions"},
                {"name": "Section C", "marks": 30, "type": "Long Answer Questions"},
            ]
        },
        "Class 11": {
            "total_marks": 100,
            "duration": "3 hours",
            "sections": [
                {"name": "Section A", "marks": 25, "type": "Objective Type (MCQs)"},
                {"name": "Section B", "marks": 45, "type": "Short Answer Questions"},
                {"name": "Section C", "marks": 30, "type": "Long Answer Questions"},
            ]
        },
        "Class 12": {
            "total_marks": 100,
            "duration": "3 hours",
            "sections": [
                {"name": "Section A", "marks": 20, "type": "Objective Type (MCQs)"},
                {"name": "Section B", "marks": 50, "type": "Short Answer Questions"},
                {"name": "Section C", "marks": 30, "type": "Long Answer Questions"},
            ]
        }
    }
    
    # Sample syllabus portions for different subjects
    syllabus_portions = {
        "Mathematics": {
            "Class 8": ["Rational Numbers", "Linear Equations", "Understanding Quadrilaterals", "Data Handling", "Squares and Square Roots"],
            "Class 9": ["Number Systems", "Polynomials", "Coordinate Geometry", "Linear Equations", "Quadrilaterals"],
            "Class 10": ["Real Numbers", "Polynomials", "Pair of Linear Equations", "Quadratic Equations", "Arithmetic Progressions"],
            "Class 11": ["Sets", "Relations and Functions", "Trigonometric Functions", "Complex Numbers", "Linear Inequalities"],
            "Class 12": ["Relations and Functions", "Inverse Trigonometric Functions", "Matrices", "Determinants", "Continuity and Differentiability"]
        },
        "Science": {
            "Class 8": ["Crop Production", "Microorganisms", "Synthetic Fibres", "Metals and Non-metals", "Force and Pressure"],
            "Class 9": ["Matter in Our Surroundings", "Is Matter Around Us Pure", "Atoms and Molecules", "Structure of the Atom", "The Fundamental Unit of Life"],
            "Class 10": ["Chemical Reactions", "Acids, Bases and Salts", "Metals and Non-metals", "Carbon and its Compounds", "Periodic Classification"],
            "Class 11": ["Some Basic Concepts of Chemistry", "Structure of Atom", "Classification of Elements", "Chemical Bonding", "States of Matter"],
            "Class 12": ["The Solid State", "Solutions", "Electrochemistry", "Chemical Kinetics", "Surface Chemistry"]
        },
        "Biology": {
            "Class 8": ["Cell Structure", "Reproduction", "Heredity", "Evolution", "Health and Disease"],
            "Class 9": ["The Fundamental Unit of Life", "Tissues", "Diversity in Living Organisms", "Why Do We Fall Ill", "Natural Resources"],
            "Class 10": ["Life Processes", "Control and Coordination", "How do Organisms Reproduce", "Heredity and Evolution", "Our Environment"],
            "Class 11": ["The Living World", "Biological Classification", "Plant Kingdom", "Animal Kingdom", "Morphology of Flowering Plants"],
            "Class 12": ["Reproduction in Organisms", "Sexual Reproduction in Flowering Plants", "Human Reproduction", "Reproductive Health", "Principles of Inheritance"]
        }
    }
    
    context = {
        'exam_patterns': exam_patterns,
        'syllabus_portions': syllabus_portions,
    }
    
    return render(request, "exam_pattern.html", context)
