/**
 * Detailed Blueprint Builder JavaScript
 * Handles dynamic form interactions and blueprint management
 */

let sectionCounter = 0;
let blueprintData = {
    version: "2.0",
    type: "detailed",
    sections: []
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Add first section by default
    addSection();
    updateSummary();
});

/**
 * Add a new section to the blueprint
 */
function addSection() {
    const template = document.getElementById('section-template');
    const sectionElement = template.content.cloneNode(true);

    // Set section index and label
    const sectionCard = sectionElement.querySelector('.section-card');
    sectionCard.dataset.sectionIndex = sectionCounter;

    const sectionLabel = sectionElement.querySelector('.section-label');
    sectionLabel.textContent = `Section ${String.fromCharCode(65 + sectionCounter)}`; // A, B, C...

    // Add to container
    document.getElementById('sections-container').appendChild(sectionElement);

    sectionCounter++;
    updateSummary();
}

/**
 * Remove a section
 */
function removeSection(button) {
    const sectionCard = button.closest('.section-card');
    sectionCard.remove();
    updateSectionLabels();
    updateSummary();
}

/**
 * Update section labels after removal
 */
function updateSectionLabels() {
    const sections = document.querySelectorAll('.section-card');
    sections.forEach((section, index) => {
        section.dataset.sectionIndex = index;
        const label = section.querySelector('.section-label');
        label.textContent = `Section ${String.fromCharCode(65 + index)}`;
    });
    sectionCounter = sections.length;
}

/**
 * Toggle passage configuration visibility
 */
function togglePassageConfig(checkbox) {
    const passageDetails = checkbox.closest('.passage-config').querySelector('.passage-details');
    if (checkbox.checked) {
        passageDetails.classList.remove('d-none');
    } else {
        passageDetails.classList.add('d-none');
    }
}

/**
 * Add a question type to a section
 */
function addQuestionType(button) {
    const template = document.getElementById('question-template');
    const questionElement = template.content.cloneNode(true);

    const questionList = button.previousElementSibling;
    questionList.appendChild(questionElement);

    // Add change listener for source selection
    const sourceSelect = questionList.lastElementChild.querySelector('.question-source');
    sourceSelect.addEventListener('change', function() {
        const chapterRow = this.closest('.question-item').querySelector('.chapter-selection');
        if (this.value === 'ncert' || this.value === 'inside_text' || this.value === 'book_back') {
            chapterRow.classList.remove('d-none');
        } else {
            chapterRow.classList.add('d-none');
        }
    });

    updateSummary();
}

/**
 * Remove a question type
 */
function removeQuestionType(button) {
    button.closest('.question-item').remove();
    updateSummary();
}

/**
 * Update blueprint summary
 */
function updateSummary() {
    const sections = document.querySelectorAll('.section-card');
    let totalSections = sections.length;
    let totalQuestions = 0;
    let totalMarks = 0;

    sections.forEach(section => {
        const sectionMarks = parseInt(section.querySelector('.section-marks').value) || 0;
        totalMarks += sectionMarks;

        const questions = section.querySelectorAll('.question-item');
        questions.forEach(question => {
            const count = parseInt(question.querySelector('.question-count').value) || 0;
            totalQuestions += count;
        });
    });

    document.getElementById('total-sections').textContent = totalSections;
    document.getElementById('total-questions').textContent = totalQuestions;
    document.getElementById('total-marks').textContent = totalMarks;
}

/**
 * Build blueprint data from form
 */
function buildBlueprintData() {
    const blueprint = {
        version: "2.0",
        type: "detailed",
        sections: []
    };

    const sections = document.querySelectorAll('.section-card');

    sections.forEach((section, index) => {
        const sectionData = {
            name: String.fromCharCode(65 + index),
            title: section.querySelector('.section-title').value || `Section ${String.fromCharCode(65 + index)}`,
            marks: parseInt(section.querySelector('.section-marks').value) || 0,
            passage_config: null,
            question_distribution: [],
            special_instructions: section.querySelector('.special-instructions').value || ""
        };

        // Passage configuration
        const enablePassage = section.querySelector('.enable-passage').checked;
        if (enablePassage) {
            sectionData.passage_config = {
                enabled: true,
                word_min: parseInt(section.querySelector('.word-min').value) || 300,
                word_max: parseInt(section.querySelector('.word-max').value) || 400,
                type: section.querySelector('.passage-type').value,
                topics: section.querySelector('.passage-topics').value.split(',').map(t => t.trim()).filter(t => t)
            };
        }

        // Question distribution
        const questions = section.querySelectorAll('.question-item');
        questions.forEach(question => {
            const qType = question.querySelector('.question-type').value;
            if (qType) {
                const questionData = {
                    type: qType,
                    count: parseInt(question.querySelector('.question-count').value) || 0,
                    marks_each: parseFloat(question.querySelector('.marks-each').value) || 1,
                    source: question.querySelector('.question-source').value,
                    difficulty: question.querySelector('.question-difficulty').value,
                    specific_chapters: []
                };

                // Add specific chapters if provided
                const chaptersInput = question.querySelector('.specific-chapters');
                if (chaptersInput && chaptersInput.value) {
                    questionData.specific_chapters = chaptersInput.value.split(',').map(c => c.trim()).filter(c => c);
                }

                questionData.total_marks = questionData.count * questionData.marks_each;
                sectionData.question_distribution.push(questionData);
            }
        });

        blueprint.sections.push(sectionData);
    });

    return blueprint;
}

/**
 * Validate blueprint
 */
async function validateBlueprint() {
    const blueprintData = buildBlueprintData();

    try {
        const response = await fetch('/api/blueprint/validate/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                blueprint_structure: blueprintData
            })
        });

        const result = await response.json();

        const statusBadge = document.getElementById('validation-status');
        const messagesDiv = document.getElementById('validation-messages');

        if (result.valid) {
            statusBadge.className = 'badge bg-success';
            statusBadge.textContent = 'Valid';
            messagesDiv.innerHTML = '<div class="alert alert-success mt-2">Blueprint structure is valid!</div>';
        } else {
            statusBadge.className = 'badge bg-danger';
            statusBadge.textContent = 'Invalid';

            let html = '<div class="alert alert-danger mt-2">';
            html += '<h6>Validation Errors:</h6><ul>';
            result.errors.forEach(error => {
                html += `<li>${error}</li>`;
            });
            html += '</ul>';

            if (result.warnings && result.warnings.length > 0) {
                html += '<h6>Warnings:</h6><ul>';
                result.warnings.forEach(warning => {
                    html += `<li>${warning}</li>`;
                });
                html += '</ul>';
            }
            html += '</div>';

            messagesDiv.innerHTML = html;
        }

        updateSummary();

    } catch (error) {
        console.error('Validation error:', error);
        alert('Error validating blueprint: ' + error.message);
    }
}

/**
 * Save blueprint
 */
async function saveBlueprint() {
    // Get basic info
    const name = document.getElementById('blueprint_name').value;
    const className = document.getElementById('class_name').value;
    const subject = document.getElementById('subject').value;

    if (!name || !className || !subject) {
        alert('Please fill in all required fields (Name, Class, Subject)');
        return;
    }

    // Validate first
    await validateBlueprint();

    const statusBadge = document.getElementById('validation-status');
    if (!statusBadge.textContent.includes('Valid')) {
        if (!confirm('Blueprint has validation errors. Save anyway?')) {
            return;
        }
    }

    const blueprintData = buildBlueprintData();

    try {
        const response = await fetch('/api/blueprint/save-detailed/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                name: name,
                class_name: className,
                subject: subject,
                blueprint_structure: blueprintData
            })
        });

        const result = await response.json();

        if (result.success) {
            alert(`Blueprint ${result.created ? 'created' : 'updated'} successfully!`);
            // Redirect to blueprint list
            window.location.href = '/blueprints/';
        } else {
            alert('Error saving blueprint: ' + (result.error || 'Unknown error'));
        }

    } catch (error) {
        console.error('Save error:', error);
        alert('Error saving blueprint: ' + error.message);
    }
}

/**
 * Load sample blueprint
 */
function loadSampleBlueprint() {
    // Clear existing sections
    document.getElementById('sections-container').innerHTML = '';
    sectionCounter = 0;

    // Set basic info
    document.getElementById('blueprint_name').value = 'Sample Class 6 English Blueprint';
    document.getElementById('class_name').value = '6';
    document.getElementById('subject').value = 'English';

    // Add Section A - Reading
    addSection();
    const sectionA = document.querySelector('.section-card[data-section-index="0"]');
    sectionA.querySelector('.section-title').value = 'Reading Comprehension';
    sectionA.querySelector('.section-marks').value = 10;
    sectionA.querySelector('.enable-passage').checked = true;
    togglePassageConfig(sectionA.querySelector('.enable-passage'));
    sectionA.querySelector('.word-min').value = 300;
    sectionA.querySelector('.word-max').value = 400;

    // Add questions to Section A
    addQuestionType(sectionA.querySelector('.question-distribution button'));
    const questionA1 = sectionA.querySelector('.question-item');
    questionA1.querySelector('.question-type').value = 'mcq';
    questionA1.querySelector('.question-count').value = 5;
    questionA1.querySelector('.marks-each').value = 1;

    addQuestionType(sectionA.querySelector('.question-distribution button'));
    const questionA2 = sectionA.querySelectorAll('.question-item')[1];
    questionA2.querySelector('.question-type').value = 'short_answer';
    questionA2.querySelector('.question-count').value = 2;
    questionA2.querySelector('.marks-each').value = 2.5;

    // Add Section B - Grammar
    addSection();
    const sectionB = document.querySelector('.section-card[data-section-index="1"]');
    sectionB.querySelector('.section-title').value = 'Grammar';
    sectionB.querySelector('.section-marks').value = 10;

    addQuestionType(sectionB.querySelector('.question-distribution button'));
    const questionB1 = sectionB.querySelector('.question-item');
    questionB1.querySelector('.question-type').value = 'fill_blanks';
    questionB1.querySelector('.question-count').value = 10;
    questionB1.querySelector('.marks-each').value = 1;

    updateSummary();
}

/**
 * Parse blueprint from text
 */
function parseFromText() {
    const modal = new bootstrap.Modal(document.getElementById('importTextModal'));
    modal.show();
}

/**
 * Import from text
 */
async function importFromText() {
    const text = document.getElementById('import-text').value;
    const className = document.getElementById('class_name').value;
    const subject = document.getElementById('subject').value;

    if (!text) {
        alert('Please enter some text to import');
        return;
    }

    try {
        const response = await fetch('/api/blueprint/parse-text/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({
                text: text,
                class_name: className,
                subject: subject
            })
        });

        const result = await response.json();

        if (result.success) {
            // Load the parsed structure
            loadBlueprintStructure(result.blueprint_structure);

            // Close modal
            bootstrap.Modal.getInstance(document.getElementById('importTextModal')).hide();

            alert('Blueprint imported successfully!');
        } else {
            alert('Error parsing text: ' + result.error);
        }

    } catch (error) {
        console.error('Import error:', error);
        alert('Error importing blueprint: ' + error.message);
    }
}

/**
 * Load blueprint structure into the form
 */
function loadBlueprintStructure(structure) {
    // Clear existing sections
    document.getElementById('sections-container').innerHTML = '';
    sectionCounter = 0;

    // Load each section
    structure.sections.forEach(sectionData => {
        addSection();
        const sectionElement = document.querySelector(`.section-card[data-section-index="${sectionCounter - 1}"]`);

        // Set section data
        sectionElement.querySelector('.section-title').value = sectionData.title || '';
        sectionElement.querySelector('.section-marks').value = sectionData.marks || 0;

        // Set passage config if present
        if (sectionData.passage_config && sectionData.passage_config.enabled) {
            sectionElement.querySelector('.enable-passage').checked = true;
            togglePassageConfig(sectionElement.querySelector('.enable-passage'));
            sectionElement.querySelector('.word-min').value = sectionData.passage_config.word_min || 300;
            sectionElement.querySelector('.word-max').value = sectionData.passage_config.word_max || 400;
            sectionElement.querySelector('.passage-type').value = sectionData.passage_config.type || 'narrative';
            sectionElement.querySelector('.passage-topics').value = (sectionData.passage_config.topics || []).join(', ');
        }

        // Add questions
        sectionData.question_distribution.forEach(questionData => {
            addQuestionType(sectionElement.querySelector('.question-distribution button'));
            const questionElement = sectionElement.querySelector('.question-list').lastElementChild;

            questionElement.querySelector('.question-type').value = questionData.type || '';
            questionElement.querySelector('.question-count').value = questionData.count || 0;
            questionElement.querySelector('.marks-each').value = questionData.marks_each || 1;
            questionElement.querySelector('.question-source').value = questionData.source || 'general';
            questionElement.querySelector('.question-difficulty').value = questionData.difficulty || 'medium';

            if (questionData.specific_chapters && questionData.specific_chapters.length > 0) {
                questionElement.querySelector('.specific-chapters').value = questionData.specific_chapters.join(', ');
            }
        });

        // Set special instructions
        if (sectionData.special_instructions) {
            sectionElement.querySelector('.special-instructions').value = sectionData.special_instructions;
        }
    });

    updateSummary();
}

/**
 * Get CSRF cookie
 */
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}