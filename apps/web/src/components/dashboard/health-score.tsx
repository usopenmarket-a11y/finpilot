import { Card, CardBody } from '@/components/ui/card';

interface HealthScoreProps {
  score: number;
}

type ScoreLabel = 'Excellent' | 'Good' | 'Fair' | 'Poor';

function getLabel(score: number): ScoreLabel {
  if (score >= 80) return 'Excellent';
  if (score >= 60) return 'Good';
  if (score >= 40) return 'Fair';
  return 'Poor';
}

function getDescription(label: ScoreLabel): string {
  switch (label) {
    case 'Excellent':
      return 'Your finances are in great shape. Keep up the strong savings rate and low debt levels.';
    case 'Good':
      return 'You\'re doing well overall. A few adjustments could push you into the excellent range.';
    case 'Fair':
      return 'There\'s room for improvement. Focus on reducing unnecessary spending and building your emergency fund.';
    case 'Poor':
      return 'Your finances need attention. Consider creating a budget and addressing high-interest debts first.';
  }
}

// Use CSS variable tokens for score colors so they are theme-aware.
function getColorVar(label: ScoreLabel): string {
  switch (label) {
    case 'Excellent':
      return 'var(--positive)';
    case 'Good':
      return 'var(--info)';
    case 'Fair':
      return 'var(--warning)';
    case 'Poor':
      return 'var(--negative)';
  }
}

function getTextClass(label: ScoreLabel): string {
  switch (label) {
    case 'Excellent':
      return 'text-positive';
    case 'Good':
      return 'text-info';
    case 'Fair':
      return 'text-warning';
    case 'Poor':
      return 'text-negative';
  }
}

export function HealthScore({ score }: HealthScoreProps) {
  const clamped = Math.max(0, Math.min(100, score));
  const label = getLabel(clamped);
  const description = getDescription(label);
  const colorVar = getColorVar(label);
  const textClass = getTextClass(label);

  // SVG circle parameters
  const size = 120;
  const strokeWidth = 10;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference - (clamped / 100) * circumference;

  return (
    <Card>
      <CardBody className="p-5">
        <h2 className="text-base font-semibold text-ink mb-4">
          Financial Health Score
        </h2>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:gap-6">
          {/* Circular SVG gauge */}
          <div className="relative mx-auto flex-shrink-0 sm:mx-0" style={{ width: size, height: size }}>
            <svg
              width={size}
              height={size}
              viewBox={`0 0 ${size} ${size}`}
              role="img"
              aria-label={`Health score: ${clamped} out of 100 — ${label}`}
            >
              {/* Background track */}
              <circle
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke="currentColor"
                strokeWidth={strokeWidth}
                className="text-surface-sunken"
              />
              {/* Progress arc */}
              <circle
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={colorVar}
                strokeWidth={strokeWidth}
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={dashOffset}
                transform={`rotate(-90 ${size / 2} ${size / 2})`}
                style={{ transition: 'stroke-dashoffset 0.6s ease' }}
              />
            </svg>
            {/* Centered score text */}
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-2xl font-semibold text-ink font-mono leading-none">
                {clamped}
              </span>
              <span className="text-xs text-ink-faint mt-0.5">/ 100</span>
            </div>
          </div>

          {/* Label + description */}
          <div className="flex-1 min-w-0">
            <span className={`text-lg font-semibold ${textClass}`}>
              {label}
            </span>
            <p className="mt-1 text-sm text-ink-muted leading-relaxed">
              {description}
            </p>
          </div>
        </div>
      </CardBody>
    </Card>
  );
}
