type RevisionedPlan = { session_id: string; revision: number }

// A slow read started during a save can finish after the save response.
// It must never replace a newer revision, including its editable draft.
export function acceptsPlanSnapshot(current: RevisionedPlan | null, next: RevisionedPlan): boolean {
  return current === null || current.session_id !== next.session_id || next.revision >= current.revision
}
