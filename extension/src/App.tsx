import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from './components/ui/tabs';
import { Button } from './components/ui/button';
import { Textarea } from './components/ui/textarea';
import { Alert, AlertDescription, AlertIcon, AlertTitle } from './components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './components/ui/card';
import { LoadingView } from './components/LoadingView';
import { DisambiguationView } from './components/DisambiguationView';
import { SolutionView } from './components/SolutionView';
import { Camera, FileText } from 'lucide-react';
import { analyzeProblem, resumeWorkflow, APIError } from './lib/api';
import { captureScreenshot, getUserId } from './lib/utils';
import type { AnalyzeResponse, InputType } from './lib/types';

type AppState = 'idle' | 'loading' | 'disambiguation' | 'solution' | 'error';

function App() {
  const [activeTab, setActiveTab] = useState<'paste' | 'screenshot'>('paste');
  const [state, setState] = useState<AppState>('idle');
  const [textInput, setTextInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<AnalyzeResponse | null>(null);

  const handleAnalyze = async (type: InputType, content: string) => {
    if (!content.trim()) {
      setError('Please enter a math problem or capture a screenshot');
      return;
    }

    setState('loading');
    setError(null);

    try {
      const userId = getUserId();
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

  const handleScreenshotCapture = async () => {
    setState('loading');
    setError(null);

    try {
      const base64Image = await captureScreenshot();
      await handleAnalyze('image', base64Image);
    } catch (err) {
      setState('error');
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to capture screenshot. Make sure you have the required permissions.'
      );
      console.error('Screenshot error:', err);
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

    if (state === 'solution' && (response?.final_response_html || response?.solution_steps)) {
      return (
        <SolutionView
          html={response.final_response_html}
          topic={response.topic}
          solutionSteps={response.solution_steps}
          finalAnswer={response.final_answer}
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
            <Camera className="h-4 w-4 mr-2" />
            Screenshot
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
              <CardTitle className="text-lg">Capture Screenshot</CardTitle>
              <CardDescription>
                Click the button below to capture the current tab and analyze any math problems visible on screen.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-col items-center justify-center p-8 border-2 border-dashed border-muted rounded-lg">
                <Camera className="h-12 w-12 text-muted-foreground mb-4" />
                <p className="text-sm text-muted-foreground text-center mb-4">
                  Make sure the math problem is visible in the current tab before capturing.
                </p>
                <Button onClick={handleScreenshotCapture} size="lg">
                  <Camera className="h-4 w-4 mr-2" />
                  Capture & Solve
                </Button>
              </div>
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


