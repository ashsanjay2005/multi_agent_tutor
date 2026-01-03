import { useState, useMemo } from 'react';
import { Card, CardContent } from './ui/card';
import { Button } from './ui/button';
import { CheckCircle2, XCircle, ChevronRight, ArrowLeft } from 'lucide-react';
import katex from 'katex';
import 'katex/dist/katex.min.css';

interface PracticeQuestion {
    question: string;
    options: string[];
    correct_index: number;
    explanation: string;
}

interface PracticeViewProps {
    topic: string;
    questions: PracticeQuestion[];
    onBack: () => void;
}

// Render LaTeX in text
function renderLatex(text: string): string {
    if (!text) return '';

    // Handle display math $$...$$
    let result = text.replace(/\$\$([^$]+)\$\$/g, (_, latex) => {
        try {
            return `<div style="margin: 8px 0; text-align: center;">${katex.renderToString(latex.trim(), { throwOnError: false, displayMode: true })}</div>`;
        } catch { return `<code>${latex}</code>`; }
    });

    // Handle inline math $...$
    result = result.replace(/\$([^$]+)\$/g, (_, latex) => {
        try {
            return katex.renderToString(latex.trim(), { throwOnError: false, displayMode: false });
        } catch { return `<code>${latex}</code>`; }
    });

    return result;
}

function TextWithMath({ text }: { text: string }) {
    const html = useMemo(() => renderLatex(text), [text]);
    return <span dangerouslySetInnerHTML={{ __html: html }} />;
}

export function PracticeView({ topic, questions, onBack }: PracticeViewProps) {
    const [currentQuestion, setCurrentQuestion] = useState(0);
    const [selectedAnswer, setSelectedAnswer] = useState<number | null>(null);
    const [showResult, setShowResult] = useState(false);
    const [score, setScore] = useState(0);
    const [completed, setCompleted] = useState(false);

    const question = questions[currentQuestion];

    const handleAnswer = (index: number) => {
        if (showResult) return; // Already answered
        setSelectedAnswer(index);
        setShowResult(true);
        if (index === question.correct_index) {
            setScore(s => s + 1);
        }
    };

    const handleNext = () => {
        if (currentQuestion < questions.length - 1) {
            setCurrentQuestion(c => c + 1);
            setSelectedAnswer(null);
            setShowResult(false);
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

                <Button onClick={onBack} variant="outline" className="w-full">
                    <ArrowLeft className="h-4 w-4 mr-2" />
                    Back to Solution
                </Button>
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

                    {/* Options */}
                    <div className="space-y-2">
                        {question.options.map((option, index) => {
                            const isSelected = selectedAnswer === index;
                            const isCorrect = index === question.correct_index;
                            const showCorrect = showResult && isCorrect;
                            const showIncorrect = showResult && isSelected && !isCorrect;

                            return (
                                <button
                                    key={index}
                                    onClick={() => handleAnswer(index)}
                                    disabled={showResult}
                                    className={`w-full text-left p-3 rounded-lg border transition-all flex items-center gap-3 ${showCorrect
                                            ? 'bg-emerald-500/20 border-emerald-500 text-emerald-300'
                                            : showIncorrect
                                                ? 'bg-red-500/20 border-red-500 text-red-300'
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

                    {/* Explanation after answer */}
                    {showResult && (
                        <div className={`mt-4 p-3 rounded-lg ${selectedAnswer === question.correct_index ? 'bg-emerald-500/10' : 'bg-amber-500/10'}`}>
                            <p className="text-sm">
                                <span className="font-medium">{selectedAnswer === question.correct_index ? '✓ Correct! ' : '✗ Incorrect. '}</span>
                                <TextWithMath text={question.explanation} />
                            </p>
                        </div>
                    )}
                </CardContent>
            </Card>

            {/* Navigation */}
            <div className="flex gap-2">
                <Button onClick={onBack} variant="outline" size="sm">
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
