import { useState, useRef } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './components/ui/tabs';
import { Button } from './components/ui/button';
import { Textarea } from './components/ui/textarea';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from './components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card';
import { LoadingView } from './components/LoadingView';
import { DisambiguationView } from './components/DisambiguationView';
import { SolutionView } from './components/SolutionView';
import { PracticeView } from './components/PracticeView';
import { Upload, FileText, ImageIcon, X } from 'lucide-react';
import { analyzeProblem, resumeWorkflow, generatePractice, APIError } from './lib/api';
import { getUserId } from './lib/utils';
import type { AnalyzeResponse, InputType, PracticeQuestion } from './lib/types';

type AppState = 'idle' | 'loading' | 'disambiguation' | 'solution' | 'practice' | 'error';

function App() {
  const [activeTab, setActiveTab] = useState<'paste' | 'screenshot'>('paste');
  const [state, setState] = useState<AppState>('idle');
  const [textInput, setTextInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<AnalyzeResponse | null>(null);
  const [uploadedImage, setUploadedImage] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [originalProblem, setOriginalProblem] = useState<string>('');
  const [practiceQuestions, setPracticeQuestions] = useState<PracticeQuestion[]>([]);
  const [practiceLoading, setPracticeLoading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleAnalyze = async (type: InputType, content: string) => {
    if (!content.trim()) {
      setError('Please enter a math problem or capture a screenshot');
      return;
    }

    setState('loading');
    setError(null);

    try {
      const userId = getUserId();
      setOriginalProblem(content); // Store for practice generation
      const result = await analyzeProblem({
        type,
        content,
        user_id: userId,
      });

      setResponse(result);

      // Determine next state based on response
      if (result.status === 'requires_disambiguation') {
        setState('disambiguation');
      } else if (result.status === 'completed') {
        setState('solution');
      } else if (result.status === 'requires_clarification') {
        setState('error');
        setError('Could not understand the problem. Please provide more details.');
      } else {
        setState('error');
        setError('An unexpected error occurred.');
      }
    } catch (err) {
      setState('error');
      if (err instanceof APIError) {
        setError(err.message);
      } else {
        setError('Failed to connect to the backend. Make sure the server is running.');
      }
      console.error('Analysis error:', err);
    }
  };

  const handleTextSubmit = () => {
    handleAnalyze('text', textInput);
  };

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.type.startsWith('image/')) {
      setError('Please select an image file (PNG, JPG, etc.)');
      return;
    }

    // Validate file size (max 10MB)
    if (file.size > 10 * 1024 * 1024) {
      setError('Image too large. Please use an image under 10MB.');
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      const base64 = e.target?.result as string;
      // Remove data URL prefix for API (keep full for preview)
      setImagePreview(base64);
      setUploadedImage(base64.split(',')[1]); // Just the base64 part
      setError(null);
    };
    reader.onerror = () => {
      setError('Failed to read image file.');
    };
    reader.readAsDataURL(file);
  };

  const handleImageSubmit = async () => {
    if (!uploadedImage) {
      setError('Please upload an image first.');
      return;
    }
    await handleAnalyze('image', uploadedImage);
  };

  const clearImage = () => {
    setUploadedImage(null);
    setImagePreview(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleTopicSelection = async (selectedTopic: string) => {
    if (!response?.thread_id) return;

    setState('loading');
    setError(null);

    try {
      const result = await resumeWorkflow({
        thread_id: response.thread_id,
        selected_topic: selectedTopic,
      });

      setResponse(result);
      setState('solution');
    } catch (err) {
      setState('error');
      if (err instanceof APIError) {
        setError(err.message);
      } else {
        setError('Failed to resume workflow.');
      }
      console.error('Resume error:', err);
    }
  };

  const handleReset = () => {
    setState('idle');
    setTextInput('');
    setError(null);
    setResponse(null);
    clearImage();
  };

  const handlePracticeClick = async () => {
    if (!response?.topic || !originalProblem) return;

    setPracticeLoading(true);
    try {
      const result = await generatePractice({
        topic: response.topic,
        original_problem: originalProblem,
        num_questions: 3
      });
      setPracticeQuestions(result.questions);
      setState('practice');
    } catch (err) {
      console.error('Practice generation error:', err);
      setError('Failed to generate practice problems. Please try again.');
    } finally {
      setPracticeLoading(false);
    }
  };

  const handleBackFromPractice = () => {
    setState('solution');
    setPracticeQuestions([]);
  };

  // Render current view based on state
  const renderContent = () => {
    if (state === 'loading') {
      return <LoadingView />;
    }

    if (state === 'disambiguation' && response?.candidate_topics) {
      return (
        <DisambiguationView
          topics={response.candidate_topics}
          onSelect={handleTopicSelection}
        />
      );
    }

    if (state === 'practice' && practiceQuestions.length > 0) {
      return (
        <PracticeView
          topic={response?.topic || ''}
          questions={practiceQuestions}
          onBack={handleBackFromPractice}
        />
      );
    }

    if (state === 'solution' && (response?.final_response_html || response?.solution_steps)) {
      return (
        <SolutionView
          html={response.final_response_html}
          topic={response.topic}
          solutionSteps={response.solution_steps}
          finalAnswer={response.final_answer}
          originalProblem={originalProblem}
          onPracticeClick={handlePracticeClick}
          practiceLoading={practiceLoading}
        />
      );
    }

    if (state === 'error') {
      return (
        <div className="space-y-4">
          <Alert variant="destructive">
            <AlertIcon className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{error || 'An unexpected error occurred'}</AlertDescription>
          </Alert>
          <Button onClick={handleReset} variant="outline" className="w-full">
            Try Again
          </Button>
        </div>
      );
    }

    // Default: Show input interface
    return (
      <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
        <TabsList className="grid w-full grid-cols-2">
          <TabsTrigger value="paste">
            <FileText className="h-4 w-4 mr-2" />
            Paste Text
          </TabsTrigger>
          <TabsTrigger value="screenshot">
            <Upload className="h-4 w-4 mr-2" />
            Upload Image
          </TabsTrigger>
        </TabsList>

        <TabsContent value="paste" className="space-y-4">
          <Card className="border-0 shadow-none">
            <CardHeader>
              <CardTitle className="text-lg">Paste Math Problem</CardTitle>
              <CardDescription>
                Copy and paste your math problem, equation, or question below.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Textarea
                placeholder="Example: Solve for x: 2x + 5 = 13"
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                rows={6}
                className="resize-none"
              />
              <Button
                onClick={handleTextSubmit}
                disabled={!textInput.trim()}
                className="w-full"
              >
                Solve Problem
              </Button>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="screenshot" className="space-y-4">
          <Card className="border-0 shadow-none">
            <CardHeader>
              <CardTitle className="text-lg">Upload Image</CardTitle>
              <CardDescription>
                Upload a screenshot or photo of your STEM problem.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Hidden file input */}
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileSelect}
                accept="image/*"
                className="hidden"
              />

              {/* Upload zone or preview */}
              {imagePreview ? (
                <div className="relative">
                  <img
                    src={imagePreview}
                    alt="Uploaded problem"
                    className="w-full rounded-lg border border-muted max-h-48 object-contain bg-slate-900"
                  />
                  <Button
                    variant="destructive"
                    size="icon"
                    className="absolute top-2 right-2 h-8 w-8"
                    onClick={clearImage}
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              ) : (
                <div
                  className="flex flex-col items-center justify-center p-8 border-2 border-dashed border-muted rounded-lg cursor-pointer hover:border-primary/50 transition-colors"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <ImageIcon className="h-12 w-12 text-muted-foreground mb-4" />
                  <p className="text-sm text-muted-foreground text-center mb-2">
                    Click to upload or drag and drop
                  </p>
                  <p className="text-xs text-muted-foreground">
                    PNG, JPG up to 10MB
                  </p>
                </div>
              )}

              <Button
                onClick={handleImageSubmit}
                disabled={!uploadedImage}
                className="w-full"
                size="lg"
              >
                <Upload className="h-4 w-4 mr-2" />
                Solve Problem
              </Button>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    );
  };

  return (
    <div className="w-full h-full bg-background text-foreground overflow-y-auto">
      <div className="sticky top-0 z-10 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 border-b">
        <div className="flex items-center justify-between p-4">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-md bg-primary flex items-center justify-center">
              <span className="text-primary-foreground font-bold text-sm">π</span>
            </div>
            <h1 className="text-lg font-semibold">AI Math Tutor</h1>
          </div>
          {state !== 'idle' && (
            <Button variant="ghost" size="sm" onClick={handleReset}>
              Reset
            </Button>
          )}
        </div>
      </div>

      <div className="p-4">
        {renderContent()}
      </div>
    </div>
  );
}

export default App;


