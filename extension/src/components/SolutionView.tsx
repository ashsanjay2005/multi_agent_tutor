import { useState, useEffect, useMemo } from 'react';
import { Card, CardContent } from './ui/card';
import { Button } from './ui/button';
import { ChevronDown, ChevronUp, CheckCircle2, Copy, RotateCcw, GraduationCap, Loader2 } from 'lucide-react';
import katex from 'katex';
import 'katex/dist/katex.min.css';

interface SolutionStep {
  step_number: number;
  title: string;
  explanation: string;
  math_expression?: string;
}

interface SolutionViewProps {
  html?: string;
  topic?: string | null;
  solutionSteps?: SolutionStep[];
  finalAnswer?: string;
  originalProblem?: string;
  onPracticeClick?: () => void;
  practiceLoading?: boolean;
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
function MathDisplay({ latex }: { latex: string }) {
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

  return (
    <div
      className="my-3 py-3 px-4 bg-slate-800/50 rounded-lg overflow-x-auto text-center"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export function SolutionView({ html, topic, solutionSteps, finalAnswer, originalProblem: _originalProblem, onPracticeClick, practiceLoading }: SolutionViewProps) {
  const [expandedStep, setExpandedStep] = useState<number | null>(1);

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

            return (
              <div key={step.step_number} className="relative">
                {/* Step Header */}
                <button
                  onClick={() => toggleStep(step.step_number)}
                  className={`w-full text-left p-3 rounded-lg transition-all flex items-start gap-3 ${isExpanded
                    ? 'bg-blue-500/10 border border-blue-500/30'
                    : 'bg-slate-800/50 hover:bg-slate-800 border border-transparent'
                    }`}
                >
                  <div className={`flex-shrink-0 h-6 w-6 rounded-full flex items-center justify-center text-xs font-bold ${isExpanded ? 'bg-blue-500 text-white' : 'bg-slate-700 text-slate-300'
                    }`}>
                    {step.step_number}
                  </div>

                  <div className="flex-1 min-w-0">
                    <span className={`font-medium text-sm ${isExpanded ? 'text-blue-400' : 'text-slate-200'}`}>
                      {step.title}
                    </span>
                  </div>

                  <div className="flex-shrink-0 text-slate-400">
                    {isExpanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                  </div>
                </button>

                {/* Expanded Content */}
                {isExpanded && (
                  <div className="mt-1 ml-9 p-3 bg-slate-900/50 rounded-lg border-l-2 border-blue-500/50">
                    {/* Explanation with inline LaTeX */}
                    <div className="text-sm text-slate-300 leading-relaxed">
                      <TextWithMath text={step.explanation} />
                    </div>

                    {/* Display Math Expression */}
                    {step.math_expression && (
                      <MathDisplay latex={step.math_expression} />
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Final Answer */}
        {finalAnswer && (
          <Card className="bg-emerald-500/10 border-emerald-500/30 mt-4">
            <CardContent className="py-3 px-4">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="h-5 w-5 text-emerald-400 flex-shrink-0" />
                <div className="min-w-0">
                  <p className="text-xs text-emerald-400/70 font-medium">Answer</p>
                  <div className="font-semibold text-emerald-300">
                    <TextWithMath text={finalAnswer} />
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
        {/* Practice Quiz Button */}
        <Button
          onClick={onPracticeClick}
          disabled={practiceLoading || !topic}
          className="w-full mt-4 bg-gradient-to-r from-purple-500 to-blue-500 hover:from-purple-600 hover:to-blue-600"
          size="lg"
        >
          {practiceLoading ? (
            <><Loader2 className="h-4 w-4 mr-2 animate-spin" />Generating Quiz...</>
          ) : (
            <><GraduationCap className="h-4 w-4 mr-2" />Practice Quiz</>
          )}
        </Button>

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

