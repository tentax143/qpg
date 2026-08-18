// Retired. This page built the old structure-style blueprint — how many questions, what type,
// what marks — which is an Exam Pattern's job and always was. (detailed-builder wrote to
// DetailedBlueprintTemplate, a model with no database table, so it could never save at all.)
//
// A blueprint now means one thing: which unit each question of a pattern is drawn from. Kept as a
// redirect rather than deleted so old bookmarks and links land on the real builder instead of 404.
import { redirect } from 'next/navigation';

export default function RetiredBlueprintPage() {
  redirect('/blueprints/plan');
}
