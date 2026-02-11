export interface User {
  id: number;
  username: string;
  first_name: string;
  last_name: string;
  email: string;
}

export interface Section {
  id: string;
  name: string;
  marks: number;
  questions_count: number;
  marks_per_question?: number;
  question_types?: string[];
  instructions?: string[];
  constraints?: Record<string, unknown>;
  subsections?: Section[];
}

export interface ExamPattern {
  id: number;
  name: string;
  description: string;
  subject: string;
  class_name: string;
  sections: Section[];
  total_marks: number;
  total_questions: number;
  pattern_source: 'manual' | 'ai_generated' | 'imported';
  ai_prompt?: string;
  created_by?: User;
  created_at: string;
  updated_at: string;
}

export interface QuestionPaper {
  id: number;
  class_name: string;
  subject: string;
  pattern: ExamPattern;
  pattern_id?: number;
  chapters: string[];
  difficulty: 'Easy' | 'Medium' | 'Hard' | 'Mixed';
  file?: string;
  status: 'queued' | 'generating' | 'done' | 'cancelled';
  task_id?: string;
  edited_content?: string;
  cost?: number;
  created_by?: User;
  created_at: string;
  updated_at: string;
}

export interface BlueprintTemplate {
  id: number;
  name: string;
  subject: string;
  class_name: string;
  description: string;
  blueprint: Record<string, unknown>;
  is_default: boolean;
  is_active: boolean;
  created_by?: User;
  created_at: string;
  updated_at: string;
}

export interface ExamBlueprint {
  id: number;
  class_name: string;
  section?: string;
  subject: string;
  code?: string;
  blueprint: Record<string, unknown>;
  template?: BlueprintTemplate;
  template_id?: number;
  is_active: boolean;
  created_by?: User;
  created_at: string;
  updated_at: string;
}

export interface ApiPaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}
