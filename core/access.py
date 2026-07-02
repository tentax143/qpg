"""Material visibility scoping — the single source of truth for "which materials/chunks can this
school see". Used by the upload listing, chapter/subject lookups, and embedding retrieval so the
access rules can never drift between them.

Model (per-material `visibility`, see Material.VISIBILITY_CHOICES):
  * own school's materials      — always visible to that school
  * institutional materials      — visible to EVERY school (cross-school sharing; off by default)
  * shared (superadmin global)   — visible only to schools granted access_shared_vector_store
  * cross-linked schools          — a school also sees the materials of any school it has been
                                    granted a SchoolVectorLink to (viewer → source); directional.
  * named vector stores           — a school also sees the materials of any VectorStore allocated
                                    to it (M2M School.vector_stores); such materials use
                                    visibility="store" so they never leak via shared/institutional.

A None school (superadmin / no-school context) sees the shared + institutional content; superadmin
listings bypass this entirely and see everything.
"""
from django.db.models import Q


def linked_source_ids(school):
    """Source-school ids whose materials `school` may read via a SchoolVectorLink (viewer→source)."""
    if school is None:
        return []
    from .models import SchoolVectorLink
    return list(SchoolVectorLink.objects.filter(viewer=school).values_list("source_id", flat=True))


def allocated_store_ids(school):
    """Named VectorStore ids allocated to `school` (M2M School.vector_stores). Its materials are
    visible to the school at retrieval, in addition to its own/institutional content."""
    if school is None:
        return []
    return list(school.vector_stores.values_list("id", flat=True))


def visibility_q(school, *, visibility_field="visibility", school_field="school", store_field="vector_store"):
    """Return a Q selecting rows visible to `school` (a School instance or None).

    `visibility_field` / `school_field` / `store_field` let the same rule apply to a related model:
    for `Material` use the defaults; for `MaterialChunk` pass visibility_field="material__visibility"
    and store_field="material__vector_store" (join to the owning Material) while keeping
    school_field="school" (the chunk's denormalized own-school column)."""
    q = Q(**{visibility_field: "institutional"})
    if school is not None:
        q |= Q(**{school_field: school})
        if getattr(school, "access_shared_vector_store", False):
            q |= Q(**{visibility_field: "shared"})
        sources = linked_source_ids(school)
        if sources:
            q |= Q(**{f"{school_field}_id__in": sources})   # cross-linked schools' materials
        stores = allocated_store_ids(school)
        if stores:
            q |= Q(**{f"{store_field}_id__in": stores})     # allocated named vector stores
    else:
        q |= Q(**{visibility_field: "shared"})
    return q
