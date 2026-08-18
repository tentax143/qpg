// Retired. BlueprintTemplates were reusable *structures*, which Exam Patterns now cover — the
// templates endpoint on patterns is the supported way to start from a premade structure.
import { redirect } from 'next/navigation';

export default function RetiredTemplateEditPage() {
  redirect('/blueprints');
}
