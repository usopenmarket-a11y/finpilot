import { Card, CardBody } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { SavingsOpportunity } from '@/lib/types';

interface SavingsOpportunitiesProps {
  opportunities: SavingsOpportunity[];
}

function formatEGP(amount: number): string {
  return new Intl.NumberFormat('en-EG', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(amount);
}

function typeIcon(opportunityType: string): string {
  switch (opportunityType.toLowerCase()) {
    case 'duplicate':
      return '\uD83D\uDCB0';   // 💰
    case 'recurring':
      return '\uD83D\uDD04';   // 🔄
    case 'fee':
      return '\u26A0\uFE0F';   // ⚠️
    case 'spike':
      return '\uD83D\uDCC8';   // 📈
    default:
      return '\uD83D\uDCA1';   // 💡
  }
}

function typeLabel(opportunityType: string): string {
  return opportunityType.charAt(0).toUpperCase() + opportunityType.slice(1);
}

export function SavingsOpportunities({ opportunities }: SavingsOpportunitiesProps) {
  if (opportunities.length === 0) {
    return (
      <Card>
        <CardBody>
          <p className="text-sm text-gray-500 dark:text-gray-400 text-center py-6">
            No savings opportunities detected. Your spending looks optimised!
          </p>
        </CardBody>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
      {opportunities.map((opp, idx) => (
        <Card key={idx}>
          <CardBody className="p-5">
            <div className="flex items-start gap-3 mb-3">
              <span className="text-2xl leading-none" role="img" aria-label={opp.opportunity_type}>
                {typeIcon(opp.opportunity_type)}
              </span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="text-sm font-semibold text-gray-900 dark:text-white">
                    {opp.title}
                  </h3>
                  <Badge variant="info">{typeLabel(opp.opportunity_type)}</Badge>
                </div>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 leading-relaxed">
                  {opp.description}
                </p>
              </div>
            </div>
            <div className="bg-brand-500/10 rounded-lg px-3 py-2 text-sm">
              <span className="text-gray-600 dark:text-gray-300">Est. monthly saving: </span>
              <span className="font-bold text-brand-500">
                EGP {formatEGP(opp.estimated_monthly_saving)}
              </span>
            </div>
          </CardBody>
        </Card>
      ))}
    </div>
  );
}
