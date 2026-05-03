import { useState, useMemo } from 'react';
import { Card, CardContent } from './ui/card';
import { Button } from './ui/button';
import { CheckCircle2, XCircle, ChevronRight, ArrowLeft } from 'lucide-react';
import katex from 'katex';
import 'katex/dist/katex.min.css';
import DOMPurify from 'dompurify';
import { logQuizResult } from '../lib/api';
import { getUserId } from '../lib/utils';

interface PracticeQuestion {
    question: string;
    options: string[];
    correct_index: number;
    explanation: string;
}

interface PracticeViewProps {
    topic: string;
    questions: PracticeQuestion[];
    onBack: (score?: { correct: number; total: number }) => void;
    onMoreQuestions?: () => void;
    loading?: boolean;
}

// Render LaTeX in text
function sanitizeHtml(html: string): string {
    return DOMPurify.sanitize(html, {
        USE_PROFILES: { html: true },
        ADD_ATTR: ['class', 'style'],
    });
}

function escapeHtml(text: string): string {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function renderLatex(text: string): string {
    if (!text) return '';

    // Handle display math $$...$$
    let result = text.replace(/\$\$([^$]+)\$\$/g, (_, latex) => {
        try {
            return `<div style="margin: 8px 0; text-align: center;">${katex.renderToString(latex.trim(), { throwOnError: false, displayMode: true })}</div>`;
        } catch { return `<code>${escapeHtml(latex)}</code>`; }
    });

    // Handle inline math $...$
    result = result.replace(/\$([^$]+)\$/g, (_, latex) => {
        try {
            return katex.renderToString(latex.trim(), { throwOnError: false, displayMode: false });
        } catch { return `<code>${escapeHtml(latex)}</code>`; }
    });

    return result;
}

function TextWithMath({ text }: { text: string }) {
    const html = useMemo(() => sanitizeHtml(renderLatex(text)), [text]);
    return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

export function PracticeView({ topic, questions, onBack, onMoreQuestions, loading }: PracticeViewProps) {
    const [currentQuestion, setCurrentQuestion] = useState(0);
    const [selectedAnswer, setSelectedAnswer] = useState<number | null>(null);
    const [showResult, setShowResult] = useState(false);
    const [score, setScore] = useState(0);
    const [completed, setCompleted] = useState(false);
    const [focusedOption, setFocusedOption] = useState<number | null>(null); // For exploring options after answer

    const question = questions[currentQuestion];

    const handleAnswer = (index: number) => {
        if (showResult) {
            // After answering, allow clicking to focus on different options
            setFocusedOption(index);
            return;
        }
        setSelectedAnswer(index);
        setShowResult(true);
        setFocusedOption(index); // Focus on selected by default

        const isCorrect = index === question.correct_index;
        if (isCorrect) {
            setScore(s => s + 1);
        }

        // Log quiz result to Backboard for adaptive profiling (fire-and-forget)
        logQuizResult({
            user_id: getUserId(),
            concept: topic?.split(' - ').pop()?.replace(/\s+/g, '_').toLowerCase() || 'unknown',
            correct: isCorrect,
            question_summary: question.question.substring(0, 100)
        });
    };

    const handleNext = () => {
        if (currentQuestion < questions.length - 1) {
            setCurrentQuestion(c => c + 1);
            setSelectedAnswer(null);
            setShowResult(false);
            setFocusedOption(null);
        } else {
            setCompleted(true);
        }
    };

    // Quiz completed - show score
    if (completed) {
        const percentage = Math.round((score / questions.length) * 100);
        return (
            <div className="space-y-4">
                <div className="text-center py-8">
                    <div className={`text-6xl mb-4 ${percentage >= 70 ? 'text-emerald-400' : 'text-amber-400'}`}>
                        {percentage >= 70 ? '🎉' : '📚'}
                    </div>
                    <h2 className="text-2xl font-bold mb-2">Quiz Complete!</h2>
                    <p className="text-xl text-slate-300">
                        You scored <span className="text-blue-400 font-bold">{score}/{questions.length}</span>
                    </p>
                    <p className="text-sm text-slate-400 mt-1">({percentage}%)</p>
                </div>

                <Card className={`${percentage >= 70 ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-amber-500/10 border-amber-500/30'}`}>
                    <CardContent className="py-4 px-4 text-center">
                        <p className="text-sm">
                            {percentage >= 70
                                ? "Great job! You've mastered this topic."
                                : "Keep practicing! Review the solution steps and try again."}
                        </p>
                    </CardContent>
                </Card>

                <div className="flex gap-2">
                    <Button
                        onClick={() => onBack({ correct: score, total: questions.length })}
                        variant="outline"
                        className="flex-1"
                    >
                        <ArrowLeft className="h-4 w-4 mr-2" />
                        Done
                    </Button>
                    {onMoreQuestions && (
                        <Button
                            onClick={onMoreQuestions}
                            className="flex-1"
                            disabled={loading}
                        >
                            {loading ? 'Generating...' : '+3 More Questions'}
                        </Button>
                    )}
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            {/* Header */}
            <div className="flex items-center justify-between pb-2 border-b border-slate-700">
                <div>
                    <h2 className="font-semibold text-base text-blue-400">Practice Quiz</h2>
                    <p className="text-xs text-slate-400">{topic}</p>
                </div>
                <div className="text-sm text-slate-400">
                    {currentQuestion + 1} / {questions.length}
                </div>
            </div>

            {/* Progress bar */}
            <div className="h-1 bg-slate-700 rounded-full overflow-hidden">
                <div
                    className="h-full bg-blue-500 transition-all duration-300"
                    style={{ width: `${((currentQuestion + (showResult ? 1 : 0)) / questions.length) * 100}%` }}
                />
            </div>

            {/* Question */}
            <Card className="border-slate-700">
                <CardContent className="pt-4 pb-4">
                    <p className="text-lg font-medium mb-4">
                        <TextWithMath text={question.question} />
                    </p>

                    {/* Options - clickable to explore after answering */}
                    <div className="space-y-2">
                        {question.options.map((option, index) => {
                            const isSelected = selectedAnswer === index;
                            const isCorrect = index === question.correct_index;
                            const showCorrect = showResult && isCorrect;
                            const showIncorrect = showResult && isSelected && !isCorrect;
                            const isFocused = showResult && focusedOption === index;

                            return (
                                <button
                                    key={index}
                                    onClick={() => handleAnswer(index)}
                                    className={`w-full text-left p-3 rounded-lg border transition-all flex items-center gap-3 ${showCorrect
                                        ? 'bg-emerald-500/20 border-emerald-500 text-emerald-300'
                                        : showIncorrect
                                            ? 'bg-red-500/20 border-red-500 text-red-300'
                                            : showResult && isFocused
                                                ? 'bg-slate-700/50 border-slate-500 ring-1 ring-slate-400'
                                                : showResult
                                                    ? 'bg-slate-800/30 border-slate-700/50 text-slate-400 hover:border-slate-500 cursor-pointer'
                                                    : isSelected
                                                        ? 'bg-blue-500/20 border-blue-500'
                                                        : 'bg-slate-800/50 border-slate-700 hover:border-slate-500'
                                        }`}
                                >
                                    <span className="flex-shrink-0 h-6 w-6 rounded-full border border-current flex items-center justify-center text-xs font-bold">
                                        {String.fromCharCode(65 + index)}
                                    </span>
                                    <span className="flex-1">
                                        <TextWithMath text={option} />
                                    </span>
                                    {showCorrect && <CheckCircle2 className="h-5 w-5 text-emerald-400" />}
                                    {showIncorrect && <XCircle className="h-5 w-5 text-red-400" />}
                                </button>
                            );
                        })}
                    </div>

                    {/* Explanation - shows for focused option */}
                    {showResult && focusedOption !== null && (
                        <div className="mt-3 animate-in slide-in-from-top-2 duration-200">
                            <div className={`flex items-start gap-2 text-sm ${focusedOption === question.correct_index ? 'text-emerald-400' : 'text-amber-400'}`}>
                                <span className="flex-shrink-0 text-xs font-bold mt-0.5">
                                    {focusedOption === question.correct_index ? '✓' : '✗'}
                                </span>
                                <p className="text-slate-300 leading-relaxed">
                                    <span className="text-slate-500 mr-1">Option {String.fromCharCode(65 + focusedOption)}:</span>
                                    <span className={`font-medium ${focusedOption === question.correct_index ? 'text-emerald-400' : 'text-red-400'}`}>
                                        {focusedOption === question.correct_index ? 'Correct! ' : 'Incorrect. '}
                                    </span>
                                    {focusedOption === question.correct_index ? (
                                        <TextWithMath text={question.explanation} />
                                    ) : (
                                        <span className="text-slate-400">
                                            This is not the right answer. The correct answer is option {String.fromCharCode(65 + question.correct_index)}.
                                        </span>
                                    )}
                                </p>
                            </div>
                            {/* Hint to explore other options */}
                            {focusedOption === selectedAnswer && (
                                <p className="text-xs text-slate-500 mt-2 ml-4">
                                    💡 Click other options to see why they&apos;re wrong
                                </p>
                            )}
                        </div>
                    )}
                </CardContent>
            </Card>

            {/* Navigation */}
            <div className="flex gap-2">
                <Button onClick={() => onBack()} variant="outline" size="sm">
                    <ArrowLeft className="h-4 w-4 mr-1" />
                    Back
                </Button>
                {showResult && (
                    <Button onClick={handleNext} className="flex-1">
                        {currentQuestion < questions.length - 1 ? (
                            <>Next Question <ChevronRight className="h-4 w-4 ml-1" /></>
                        ) : (
                            'See Results'
                        )}
                    </Button>
                )}
            </div>
        </div>
    );
}
