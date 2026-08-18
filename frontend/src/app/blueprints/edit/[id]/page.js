// Retired in favour of /blueprints/plan?id=<id>, which edits the unit map with the pattern's real
// question numbers in front of you. The id is carried across so an old link still opens the right
// blueprint.
import { redirect } from 'next/navigation';

export default async function RetiredBlueprintEditPage({ params }) {
  const { id } = await params;
  redirect(`/blueprints/plan?id=${encodeURIComponent(id)}`);
}
