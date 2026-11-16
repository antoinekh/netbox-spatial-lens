"""
The tags in use on a drawing, for the Tags finder.

A drawing offers only the tags its own racks or devices carry, each with how many carry it, so
the list is short and every row narrows the drawing to something.
"""

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = (
    'TagCount',
    'tag_slugs',
    'tags_in_use',
)


@dataclass
class TagCount:
    tag: object
    count: int


def tags_in_use(objects: Iterable) -> list[TagCount]:
    """
    Every tag on `objects`, with how many of them carry it, in name order.

    Reads `obj.tags.all()`, so the caller prefetches the tags or this costs a query per object.
    """
    counts: dict[int, TagCount] = {}
    for obj in objects:
        for tag in obj.tags.all():
            if tag.pk in counts:
                counts[tag.pk].count += 1
            else:
                counts[tag.pk] = TagCount(tag=tag, count=1)
    return sorted(counts.values(), key=lambda item: item.tag.name.lower())


def tag_slugs(model, pks: Iterable[int]) -> dict[int, list[str]]:
    """
    The tag slugs of each of `pks`, which are objects of `model`, in one query and in tag order.

    For a drawing of thousands of objects that needs the slugs alone. `prefetch_related('tags')`
    builds a queryset per object, which for the devices of a whole hall is most of the request.
    An object with no tag is absent.
    """
    from django.contrib.contenttypes.models import ContentType
    from extras.models import TaggedItem

    rows = (
        TaggedItem.objects.filter(content_type=ContentType.objects.get_for_model(model), object_id__in=pks)
        .order_by('tag__weight', 'tag__name')
        .values_list('object_id', 'tag__slug')
    )
    slugs: dict[int, list[str]] = {}
    for object_id, slug in rows:
        slugs.setdefault(object_id, []).append(slug)
    return slugs
