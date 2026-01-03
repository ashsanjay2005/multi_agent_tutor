import { useState } from 'react';
import { Button } from './ui/button';
import { RadioGroup, RadioGroupItem } from './ui/radio-group';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { HelpCircle } from 'lucide-react';

interface DisambiguationViewProps {
  topics: string[];
  onSelect: (topic: string) => void;
}

export function DisambiguationView({ topics, onSelect }: DisambiguationViewProps) {
  const [selectedTopic, setSelectedTopic] = useState<string>(topics[0] || '');

  const handleSubmit = () => {
    if (selectedTopic) {
      onSelect(selectedTopic);
    }
  };

  return (
    <Card className="border-0 shadow-none">
      <CardHeader className="text-center pb-4">
        <div className="mx-auto mb-2 h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center">
          <HelpCircle className="h-6 w-6 text-primary" />
        </div>
        <CardTitle className="text-lg">Topic Clarification Needed</CardTitle>
        <CardDescription>
          Multiple topics were detected. Please select the one that best matches your problem.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <RadioGroup value={selectedTopic} onValueChange={setSelectedTopic}>
          {topics.map((topic) => (
            <RadioGroupItem key={topic} value={topic}>
              <span className="text-sm font-medium">{topic}</span>
            </RadioGroupItem>
          ))}
        </RadioGroup>
        <Button 
          onClick={handleSubmit} 
          disabled={!selectedTopic}
          className="w-full"
        >
          Continue with Selected Topic
        </Button>
      </CardContent>
    </Card>
  );
}


