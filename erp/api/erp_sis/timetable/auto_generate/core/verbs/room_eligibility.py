from ..registry import Verb, register_verb
from ..room_constraints import eligible_room_indices, restrict_room_for_assignment


@register_verb("room_eligibility", supports=["assignment"], kind="both", description="Ràng buộc phòng hợp lệ theo môn/lớp")
class RoomEligibility(Verb):
	def _apply(self, ctx, subject_set, kind: str, weight: int):
		if not (ctx.use_room_vars and ctx.room):
			return
		inp = ctx.inp
		for class_id, ts_id in subject_set:
			valid = eligible_room_indices(inp, class_id, ts_id, ctx.room_index_map)
			if not valid:
				continue
			restrict_room_for_assignment(
				ctx,
				class_id,
				ts_id,
				valid,
				kind=kind,
				weight=weight,
				tag="eligible",
			)

	def apply_hard(self, ctx, subject_set, params):
		self._apply(ctx, list(subject_set or []), kind="hard", weight=0)

	def build_soft(self, ctx, subject_set, params, weight: int):
		self._apply(ctx, list(subject_set or []), kind="soft", weight=weight)
		return []

