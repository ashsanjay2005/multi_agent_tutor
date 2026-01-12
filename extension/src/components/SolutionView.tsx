import { useState, useMemo, useCallback, useEffect } from 'react';
import { Card, CardContent } from './ui/card';
import { Button } from './ui/button';
import { ChevronDown, CheckCircle2, Copy, GraduationCap, Loader2, Layers, RotateCcw } from 'lucide-react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import { expandStep } from '../lib/api';
import type { SolutionStep, SubStep, StopReason } from '../lib/types';

interface SolutionViewProps {
  html?: string;
  topic?: string | null;
  solutionSteps?: SolutionStep[];
  finalAnswer?: string;
  originalProblem?: string;
  onPracticeClick?: () => void;
  practiceLoading?: boolean;
  initialSubSteps?: Record<string, SubStep[]>;  // Loaded from history
  onSubStepsChange?: (subSteps: Record<string, SubStep[]>) => void;  // Save to history
  hasStoredQuiz?: boolean;  // True if there's a saved quiz to review
  onReviewQuiz?: () => void;  // Callback to review stored quiz
}

// ============================================================================
// DEPTH-BASED STYLING HELPERS
// ============================================================================

// Get hierarchy line style based on depth
function getHierarchyLineStyle(depth: number): { width: string; opacity: number; color: string } {
  switch (depth) {
    case 0:
    case 1:
      return { width: '2px', opacity: 1, color: 'rgb(59, 130, 246)' }; // Level 1: solid blue
    case 2:
      return { width: '1.5px', opacity: 0.6, color: 'rgb(59, 130, 246)' }; // Level 2: 60% opacity
    default:
      return { width: '1px', opacity: 0.3, color: 'rgb(59, 130, 246)' }; // Level 3+: 30% opacity
  }
}

// Get semantic tag for deep nesting (depth >= 3)
const SEMANTIC_TAGS = ['Concept', 'Definition', 'Deep Dive', 'Detail', 'Insight'];
function getSemanticTag(label: string): string {
  // Use label hash to consistently pick a tag
  const hash = label.split('').reduce((a, c) => a + c.charCodeAt(0), 0);
  return SEMANTIC_TAGS[hash % SEMANTIC_TAGS.length];
}

// Parse text and render inline LaTeX ($...$) and display LaTeX ($$...$$)
function renderLatexInText(text: string): string {
  if (!text) return '';

  // First handle display math ($$...$$) - add block spacing
  let result = text.replace(/\$\$([^$]+)\$\$/g, (_, latex) => {
    try {
      const rendered = katex.renderToString(latex.trim(), {
        throwOnError: false,
        displayMode: true,
        trust: true,
      });
      // Wrap in div with vertical margin for spacing
      return `<div style="margin: 16px 0; text-align: center;">${rendered}</div>`;
    } catch (e) {
      return `<code>${latex}</code>`;
    }
  });

  // Then handle inline math ($...$) - add small horizontal spacing
  result = result.replace(/\$([^$]+)\$/g, (_, latex) => {
    try {
      const rendered = katex.renderToString(latex.trim(), {
        throwOnError: false,
        displayMode: false,
        trust: true,
      });
      // Add small margin around inline math
      return `<span style="margin: 0 2px;">${rendered}</span>`;
    } catch (e) {
      return `<code>${latex}</code>`;
    }
  });

  return result;
}

// Component to render text with inline LaTeX
function TextWithMath({ text }: { text: string }) {
  const renderedHtml = useMemo(() => renderLatexInText(text), [text]);

  return (
    <span
      className="latex-text"
      dangerouslySetInnerHTML={{ __html: renderedHtml }}
    />
  );
}

// Render display LaTeX (for math_expression field)
// Ghost styling: no background at depth > 1, just centered with accent border
function MathDisplay({ latex, depth = 0 }: { latex: string; depth?: number }) {
  const [html, setHtml] = useState('');

  useEffect(() => {
    if (!latex) return;
    try {
      // Comprehensive LaTeX cleaning
      let cleanLatex = latex
        // Remove leading/trailing $ or $$
        .replace(/^[\$\s]+|[\$\s]+$/g, '')
        // Fix common issue: "equation1$ $equation2" -> "equation1 \\\\ equation2" (newline)
        .replace(/\$\s*\$/g, ' \\\\\\\\ ')
        // Remove any remaining standalone $ signs
        .replace(/\$/g, ' ')
        // Clean up multiple spaces
        .replace(/\s+/g, ' ')
        .trim();

      // If the result looks like multiple equations, wrap in aligned environment
      if (cleanLatex.includes('\\\\')) {
        cleanLatex = `\\begin{aligned} ${cleanLatex} \\end{aligned}`;
      }

      const rendered = katex.renderToString(cleanLatex, {
        throwOnError: false,
        displayMode: true,
        trust: true,
      });
      setHtml(rendered);
    } catch (e) {
      console.error('KaTeX error:', e, 'Original:', latex);
      // Fallback: try to render as-is with error tolerance
      try {
        const fallback = katex.renderToString(latex.replace(/\$/g, ''), {
          throwOnError: false,
          displayMode: true,
          trust: true,
        });
        setHtml(fallback);
      } catch {
        setHtml(`<pre style="text-align: left; font-size: 12px; overflow-x: auto;">${latex}</pre>`);
      }
    }
  }, [latex]);

  if (!latex) return null;

  // Ghost styling for nested math blocks (depth > 1)
  const isGhost = depth > 1;

  return (
    <div
      className={`my-3 py-3 ${isGhost
        ? 'border-l-2 border-teal-500/40 pl-4'  // Ghost: accent border only
        : 'px-4 bg-slate-800/50 rounded-lg'     // Normal: background
        }`}
    >
      {/* Math container - left aligned with thin scrollbar */}
      <div
        className="math-scroll-container"
        style={{
          overflowX: 'auto',
          overflowY: 'visible',
          paddingBottom: '2px',
          scrollbarWidth: 'thin',  // Firefox
        }}
      >
        <div
          className="katex-wrapper"
          style={{
            display: 'inline-block',
            transform: html.length > 2000 ? 'scale(0.9)' : 'scale(1)',
            transformOrigin: 'left center',
          }}
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>
    </div>
  );
}

export function SolutionView({
  html, topic, solutionSteps, finalAnswer, originalProblem,
  onPracticeClick, practiceLoading,
  initialSubSteps, onSubStepsChange,
  hasStoredQuiz, onReviewQuiz
}: SolutionViewProps) {
  const [expandedStep, setExpandedStep] = useState<number | null>(1);
  // Track sub-steps for each step by step path - initialize from history
  const [subStepsMap, setSubStepsMap] = useState<Record<string, SubStep[]>>(initialSubSteps || {});
  const [expandingPath, setExpandingPath] = useState<string | null>(null);
  const [stopReasons, setStopReasons] = useState<Record<string, { reason: StopReason; message: string }>>({});

  const toggleStep = (stepNum: number) => {
    setExpandedStep(expandedStep === stepNum ? null : stepNum);
  };

  const copyToClipboard = () => {
    if (!solutionSteps) return;
    const text = solutionSteps
      .map(s => `Step ${s.step_number}: ${s.title}\n${s.explanation}`)
      .join('\n\n');
    navigator.clipboard.writeText(text + (finalAnswer ? `\n\nAnswer: ${finalAnswer}` : ''));
  };

  const handleExpandStep = useCallback(async (
    stepId: string,
    stepPath: string,
    step: { title: string; explanation: string; math_expression?: string },
    depth: number
  ) => {
    if (expandingPath || depth >= 3) return;

    setExpandingPath(stepPath);
    try {
      const result = await expandStep({
        step_id: stepId,
        step_path: stepPath,
        step_title: step.title,
        step_explanation: step.explanation,
        step_math: step.math_expression,
        problem_statement: originalProblem || '',
        topic: topic || '',
        current_depth: depth,
      });

      if (result.stop_reason) {
        setStopReasons(prev => ({
          ...prev,
          [stepPath]: { reason: result.stop_reason!, message: result.message || '' }
        }));
      } else if (result.sub_steps.length > 0) {
        const newMap = { ...subStepsMap, [stepPath]: result.sub_steps };
        setSubStepsMap(newMap);
        // Persist to history
        onSubStepsChange?.(newMap);
      }
    } catch (err) {
      console.error('Expand step failed:', err);
    } finally {
      setExpandingPath(null);
    }
  }, [expandingPath, originalProblem, topic, subStepsMap, onSubStepsChange]);

  // Render step-by-step solution
  if (solutionSteps && solutionSteps.length > 0) {
    return (
      <div className="space-y-3">
        {/* Topic Header */}
        {topic && (
          <div className="pb-2 border-b border-slate-700">
            <h2 className="font-semibold text-base text-blue-400">{topic.split(' - ').pop()}</h2>
            <p className="text-xs text-slate-400">Step-by-step solution</p>
          </div>
        )}

        {/* Solution Steps */}
        <div className="space-y-2">
          {solutionSteps.map((step) => {
            const isExpanded = expandedStep === step.step_number;
            const stepPath = String(step.step_number);

            return (
              <div key={step.step_number} className="relative">
                {/* Step Header - Elevated card style */}
                <button
                  onClick={() => toggleStep(step.step_number)}
                  className={`w-full text-left p-4 rounded-xl transition-all flex items-start gap-3 ${isExpanded
                    ? 'bg-slate-800/80 shadow-lg shadow-blue-500/5 ring-1 ring-blue-500/20'
                    : 'bg-slate-800/40 hover:bg-slate-800/60 shadow-md'
                    }`}
                >
                  {/* Step number badge */}
                  <div className={`flex-shrink-0 h-7 w-7 rounded-lg flex items-center justify-center text-xs font-bold transition-all ${isExpanded
                    ? 'bg-gradient-to-br from-blue-500 to-indigo-600 text-white shadow-md shadow-blue-500/30'
                    : 'bg-slate-700/80 text-slate-300'
                    }`}>
                    {step.step_number}
                  </div>

                  <div className="flex-1 min-w-0">
                    <span className={`font-medium text-sm leading-tight ${isExpanded ? 'text-white' : 'text-slate-200'}`}>
                      {step.title}
                    </span>
                  </div>

                  <div className={`flex-shrink-0 transition-transform ${isExpanded ? 'rotate-180' : ''}`}>
                    <ChevronDown className={`h-4 w-4 ${isExpanded ? 'text-blue-400' : 'text-slate-500'}`} />
                  </div>
                </button>

                {/* Expanded Content - Clean spatial hierarchy */}
                {isExpanded && (
                  <div className="mt-2 ml-4 pl-6 border-l border-slate-700/50">
                    {/* Explanation with inline LaTeX */}
                    <div className="text-sm text-slate-300 leading-relaxed py-3">
                      <TextWithMath text={step.explanation} />
                    </div>

                    {/* Display Math Expression */}
                    {step.math_expression && (
                      <MathDisplay latex={step.math_expression} />
                    )}

                    {/* Sub-steps (if expanded) with fading hierarchy */}
                    {subStepsMap[stepPath] && (() => {
                      const depth2Style = getHierarchyLineStyle(2);
                      return (
                        <div
                          className="mt-4 space-y-4 pl-4"
                          style={{
                            borderLeftWidth: depth2Style.width,
                            borderLeftStyle: 'solid',
                            borderLeftColor: `rgba(100, 116, 139, ${depth2Style.opacity})`
                          }}
                        >
                          {subStepsMap[stepPath].map((sub) => {
                            const subDepth = stepPath.split('.').length + 1;
                            const useSemanticLabel = subDepth >= 3;

                            return (
                              <div key={sub.id} className="text-xs bg-slate-800/30 rounded-lg p-3">
                                {/* Label: numeric or semantic */}
                                <div className="font-medium mb-2 flex items-center gap-2">
                                  {useSemanticLabel ? (
                                    <>
                                      <span className="px-2 py-0.5 rounded-md text-[10px] bg-indigo-500/15 text-indigo-300 font-medium">
                                        {getSemanticTag(sub.label)}
                                      </span>
                                      <span className="text-slate-200">{sub.title}</span>
                                    </>
                                  ) : (
                                    <span className="text-slate-200">
                                      <span className="text-blue-400 font-semibold">{sub.label}</span>: {sub.title}
                                    </span>
                                  )}
                                </div>
                                <div className="text-slate-400 leading-relaxed">
                                  <TextWithMath text={sub.explanation} />
                                </div>
                                {sub.math_expression && (
                                  <div className="ml-1 mt-1">
                                    <MathDisplay latex={sub.math_expression} depth={subDepth} />
                                  </div>
                                )}
                                {/* Recursive expand for sub-steps */}
                                {sub.can_expand && !subStepsMap[sub.label] && !stopReasons[sub.label] && (
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    className="h-6 px-2 mt-1.5 text-xs text-slate-400 hover:text-blue-300"
                                    onClick={() => handleExpandStep(
                                      sub.id,
                                      sub.label,
                                      sub,
                                      stepPath.split('.').length
                                    )}
                                    disabled={expandingPath === sub.label}
                                  >
                                    {expandingPath === sub.label ? (
                                      <><Loader2 className="h-3 w-3 mr-1 animate-spin" /> Expanding...</>
                                    ) : (
                                      <><Layers className="h-3 w-3 mr-1" /> Break down</>
                                    )}
                                  </Button>
                                )}
                                {/* Show stop reason for sub-step */}
                                {stopReasons[sub.label] && (
                                  <div className="ml-1 mt-1 text-xs text-amber-400/70">
                                    {stopReasons[sub.label].message}
                                  </div>
                                )}
                                {/* Show nested sub-steps (depth 3+) with fading lines */}
                                {subStepsMap[sub.label] && (() => {
                                  const depth3Style = getHierarchyLineStyle(3);
                                  return (
                                    <div
                                      className="mt-2 ml-1 space-y-2 pl-3"
                                      style={{
                                        borderLeftWidth: depth3Style.width,
                                        borderLeftStyle: 'solid',
                                        borderLeftColor: `rgba(59, 130, 246, ${depth3Style.opacity})`
                                      }}
                                    >
                                      {subStepsMap[sub.label].map(nested => (
                                        <div key={nested.id} className="text-xs">
                                          {/* Semantic label for depth 3+ */}
                                          <div className="flex items-center gap-2 mb-1">
                                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-purple-500/15 text-purple-300/80 font-normal">
                                              {getSemanticTag(nested.label)}
                                            </span>
                                            <span className="text-slate-400">{nested.title}</span>
                                          </div>
                                          <div className="text-slate-500 ml-1">
                                            <TextWithMath text={nested.explanation} />
                                          </div>
                                          {nested.math_expression && (
                                            <div className="ml-1 mt-1">
                                              <MathDisplay latex={nested.math_expression} depth={3} />
                                            </div>
                                          )}
                                        </div>
                                      ))}
                                    </div>
                                  );
                                })()}
                              </div>
                            );
                          })}
                        </div>
                      );
                    })()}

                    {/* Stop reason message */}
                    {stopReasons[stepPath] && (
                      <div className="mt-2 text-xs text-amber-400/70 flex items-center gap-1">
                        <span>⚠</span> {stopReasons[stepPath].message}
                      </div>
                    )}

                    {/* Break Down Button - only if no sub-steps yet and no stop reason */}
                    {!subStepsMap[stepPath] && !stopReasons[stepPath] && (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="mt-3 h-7 text-xs text-slate-400 hover:text-blue-300 border border-slate-700 hover:border-blue-500/50"
                        onClick={() => handleExpandStep(
                          step.id || `step-${step.step_number}`,
                          stepPath,
                          step,
                          0
                        )}
                        disabled={expandingPath === stepPath}
                      >
                        {expandingPath === stepPath ? (
                          <><Loader2 className="h-3 w-3 mr-1 animate-spin" /> Breaking down...</>
                        ) : (
                          <><Layers className="h-3 w-3 mr-1" /> Break down this step</>
                        )}
                      </Button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Final Answer - Clean, subtle success styling */}
        {finalAnswer && (
          <div className="mt-6 pt-4 border-t border-slate-700/50">
            <div className="flex items-start gap-3">
              <div className="flex-shrink-0 h-6 w-6 rounded-full bg-emerald-500/20 flex items-center justify-center">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs text-slate-500 font-medium mb-1">Final Answer</p>
                <div className="text-sm text-slate-200 leading-relaxed">
                  <TextWithMath text={finalAnswer} />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Practice Quiz - Interactive Badge/Pills */}
        <div className="mt-5 flex flex-col items-center gap-2">
          {/* Review Previous Quiz (if stored) */}
          {hasStoredQuiz && onReviewQuiz && (
            <button
              onClick={onReviewQuiz}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-emerald-500/15 hover:bg-emerald-500/25 border border-emerald-500/30 hover:border-emerald-400/50 transition-all"
            >
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              <span className="text-sm font-medium text-slate-200">Review Previous Quiz</span>
              <span className="text-xs px-1.5 py-0.5 rounded-full bg-emerald-500/30 text-emerald-300">
                Saved
              </span>
            </button>
          )}

          {/* Generate New Quiz */}
          <button
            onClick={onPracticeClick}
            disabled={practiceLoading || !topic}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-full bg-gradient-to-r from-indigo-500/20 to-purple-500/20 hover:from-indigo-500/30 hover:to-purple-500/30 border border-indigo-500/30 hover:border-indigo-400/50 transition-all disabled:opacity-50"
          >
            {practiceLoading ? (
              <Loader2 className="h-4 w-4 animate-spin text-indigo-400" />
            ) : (
              <GraduationCap className="h-4 w-4 text-indigo-400" />
            )}
            <span className="text-sm font-medium text-slate-200">
              {practiceLoading ? 'Generating...' : hasStoredQuiz ? 'Generate New Quiz' : '3 Questions Available'}
            </span>
            {!practiceLoading && !hasStoredQuiz && (
              <span className="text-xs px-1.5 py-0.5 rounded-full bg-indigo-500/30 text-indigo-300">
                Quiz
              </span>
            )}
          </button>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-2 pt-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => window.location.reload()}
            className="flex-1"
          >
            <RotateCcw className="h-4 w-4 mr-2" />
            New Problem
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={copyToClipboard}
          >
            <Copy className="h-4 w-4 mr-2" />
            Copy
          </Button>
        </div>
      </div>
    );
  }

  // Fallback: render HTML
  if (html) {
    return (
      <div className="space-y-4">
        <Card className="border-0 shadow-none">
          <CardContent className="pt-6">
            <div
              className="prose prose-invert prose-sm max-w-none"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          </CardContent>
        </Card>
        <Button
          variant="outline"
          size="sm"
          onClick={() => window.location.reload()}
          className="w-full"
        >
          New Problem
        </Button>
      </div>
    );
  }

  return (
    <div className="text-center py-8 text-slate-400">
      <p>No solution available</p>
    </div>
  );
}

