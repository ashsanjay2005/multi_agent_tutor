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

export interface SolutionStep {
    step_number: number;
    title: string;
    explanation: string;
    math_expression?: string;
}

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
