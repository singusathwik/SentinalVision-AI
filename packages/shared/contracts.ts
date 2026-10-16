export type JobState = 'queued' | 'running' | 'completed' | 'failed' | 'canceled';
export type ReviewStatus = 'confirmed' | 'false_alarm' | 'needs_review';
export interface SafetyEvent { id: string; rule_id: string; timestamp: number; track_ids: number[]; confidence: number; reason: string; status: ReviewStatus; }
