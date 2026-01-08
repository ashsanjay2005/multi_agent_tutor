/**
 * TypeScript types matching the backend Pydantic models
 */

export type InputType = 'text' | 'image';

export type AnalysisStatus =
    | 'completed'
    | 'requires_disambiguation'
    | 'requires_clarification'
    | 'error';

export interface AnalyzeRequest {
    type: InputType;
    content: string;
    user_id: string;
    thread_id?: string;
}

// SolutionStep is defined below with sub_step support

export interface AnalyzeResponse {
    thread_id: string;
    status: AnalysisStatus;
    requires_user_action: boolean;
    final_response_html?: string;
    candidate_topics?: string[];
    topic?: string;
    confidence_score?: number;
    solution_steps?: SolutionStep[];
    final_answer?: string;
    extracted_problem?: string;
}

export interface ResumeRequest {
    thread_id: string;
    selected_topic: string;
}

export interface ExplainStepRequest {
    step_text: string;
    context: string;
    topic: string;
}

export interface ExplainStepResponse {
    explanation: string;
    topic: string;
}

export interface HealthResponse {
    status: string;
    version: string;
    environment: string;
}

// Practice Quiz Types
export interface PracticeQuestion {
    question: string;
    options: string[];
    correct_index: number;
    explanation: string;
}

export interface PracticeRequest {
    topic: string;
    original_problem: string;
    num_questions?: number;
}

export interface PracticeResponse {
    topic: string;
    questions: PracticeQuestion[];
}

// Sub-step expansion types
export type StopReason = 'atomic' | 'max_depth' | 'loop_risk' | 'insufficient_context';

export interface SolutionStep {
    step_number: number;
    title: string;
    explanation: string;
    math_expression?: string;
    // Extension for recursive sub-steps
    id?: string;           // Stable unique ID
    label?: string;        // Display label (e.g., "1.2.1")
    sub_steps?: SolutionStep[];
    can_expand?: boolean;  // Default true
    depth?: number;        // 0=top-level
}

export interface PreviousStepSummary {
    label: string;
    title: string;
    summary: string;
}

export interface ExpandStepRequest {
    step_id: string;
    step_path: string;
    step_title: string;
    step_explanation: string;
    step_math?: string;
    problem_statement: string;
    topic: string;
    current_depth: number;
    previous_steps?: PreviousStepSummary[];
}

export interface SubStep {
    id: string;
    label: string;
    order: number;
    title: string;
    explanation: string;
    math_expression?: string;
    can_expand: boolean;
}

export interface ExpandStepResponse {
    sub_steps: SubStep[];
    can_expand: boolean;
    stop_reason?: StopReason;
    message?: string;
}
