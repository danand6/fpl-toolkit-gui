export const FEATURE_LIST = [
  {
    id: 'my-team-summary',
    label: 'My Team Summary',
    endpoint: '/api/features/my-team-summary'
  },
  {
    id: 'smart-captaincy',
    label: 'Smart Captaincy',
    endpoint: '/api/features/smart-captaincy'
  },
  {
    id: 'current-captain',
    label: 'Current Captaincy',
    endpoint: '/api/features/current-captain',
    promptText: 'Who is my captain right now?'
  },
  {
    id: 'clear-output',
    label: 'Clear Output',
    type: 'clear'
  },
  {
    id: 'differential-hunter',
    label: 'Differential Hunter',
    endpoint: '/api/features/differential-hunter',
    type: 'options',
    options: [
      { label: 'Sort by Form', value: 'form' },
      { label: 'Sort by Points', value: 'total_points' },
      { label: 'Sort by ICT', value: 'ict_index' }
    ],
    defaultOption: 'form'
  },
  {
    id: 'transfer-suggester',
    label: 'Transfer Suggester',
    endpoint: '/api/features/transfer-suggester'
  },
  {
    id: 'predicted-top-performers',
    label: 'Predict Top Performers',
    endpoint: '/api/features/predicted-top-performers'
  },
  {
    id: 'ai-predictions',
    label: 'AI Top Performers',
    endpoint: '/api/features/ai-predictions'
  },
  {
    id: 'ai-team-performance',
    label: 'Squad Projection',
    endpoint: '/api/features/ai-team-performance',
    promptText: 'How will my squad perform next week?'
  },
  {
    id: 'chip-advice',
    label: 'Chip Strategy',
    endpoint: '/api/features/chip-advice',
    promptText: 'When should I use my chips?'
  },
  {
    id: 'league-current',
    label: 'Current League Table',
    endpoint: '/api/features/league-current',
    promptText: 'Show my current league standings'
  },
  {
    id: 'dream-team',
    label: 'Dream Team Optimizer',
    endpoint: '/api/features/dream-team'
  },
  {
    id: 'league-predictions',
    label: 'League Predictions',
    endpoint: '/api/features/league-predictions'
  },
  {
    id: 'injury-risk',
    label: 'Injury/Risk Analyzer',
    endpoint: '/api/features/injury-risk'
  },
  {
    id: 'quadrant-analysis',
    label: 'Quadrant Analysis',
    endpoint: '/api/features/quadrant-analysis'
  }
];

export const FEATURE_BY_ID = FEATURE_LIST.reduce((acc, feature) => {
  acc[feature.id] = feature;
  return acc;
}, {});

export const FEATURE_PROMPTS = FEATURE_LIST.filter((feature) => feature.type !== 'clear').map((feature) => ({
  id: feature.id,
  label: feature.label,
  endpoint: feature.endpoint,
  type: feature.type,
  options: feature.options,
  defaultOption: feature.defaultOption,
  promptText: feature.promptText ?? `Show me ${feature.label.toLowerCase()}`,
}));
