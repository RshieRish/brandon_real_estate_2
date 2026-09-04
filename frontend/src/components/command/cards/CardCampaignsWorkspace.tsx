'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import {
  ArrowRight,
  CalendarDots,
  CardsThree,
  CheckCircle,
  Plus,
  ShieldCheck,
  WarningCircle,
} from '@phosphor-icons/react';
import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  cardsApi,
  type CardCampaignListItem,
  type CardsApi,
} from '@/lib/command/cards';
import { CommandModuleHeader } from '../ui/CommandModuleHeader';
import { CommandStatePanel } from '../ui/CommandStatePanel';

const spring = { type: 'spring' as const, stiffness: 100, damping: 20 };
const monthNames = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
] as const;

type LoadState = 'loading' | 'ready' | 'error';

export type CardCampaignsWorkspaceProps = Readonly<{
  api?: CardsApi;
  initialCreate?: boolean;
}>;

function money(cents: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(cents / 100);
}

function statusLabel(status: CardCampaignListItem['status']): string {
  const labels: Readonly<Record<CardCampaignListItem['status'], string>> = {
    draft: 'Draft',
    needs_addresses: 'Needs addresses',
    needs_connection: 'Connection required',
    ready_for_review: 'Ready for review',
    approved: 'Approved',
    sending: 'Sending',
    sent: 'Sent',
    partially_sent: 'Partially sent',
    failed: 'Not sent',
    delivery_uncertain: 'Needs verification',
  };
  return labels[status];
}

function CampaignCard({ campaign }: Readonly<{ campaign: CardCampaignListItem }>) {
  const warning = campaign.status === 'needs_addresses'
    || campaign.status === 'needs_connection'
    || campaign.status === 'partially_sent'
    || campaign.status === 'failed'
    || campaign.status === 'delivery_uncertain';
  const StatusIcon = warning ? WarningCircle : CheckCircle;

  return (
    <motion.article
      layout
      className="command-card-campaign"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={spring}
    >
      <div className="command-card-campaign-topline">
        <span className={`command-card-status is-${campaign.status}`}>
          <StatusIcon aria-hidden="true" size={17} weight="fill" />
          {statusLabel(campaign.status)}
        </span>
        <span>{monthNames[campaign.month - 1]}</span>
      </div>
      <h2>{campaign.title}</h2>
      <div className="command-card-campaign-metrics" aria-label="Campaign counts">
        <span><strong>{campaign.sendable_recipients}</strong> ready</span>
        <span><strong>{campaign.missing_address_count}</strong> need addresses</span>
        <span><strong>{money(campaign.estimated_cost_cents)}</strong> estimated</span>
      </div>
      <Link
        href={`/admin/command/cards/${campaign.id}`}
        className="command-card-link command-touch-target"
      >
        Open review <ArrowRight aria-hidden="true" size={18} />
      </Link>
    </motion.article>
  );
}

export function CardCampaignsWorkspace({
  api = cardsApi,
  initialCreate = false,
}: CardCampaignsWorkspaceProps) {
  const router = useRouter();
  const reduceMotion = useReducedMotion();
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [campaigns, setCampaigns] = useState<readonly CardCampaignListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [showCreate, setShowCreate] = useState(initialCreate);
  const [month, setMonth] = useState(() => new Date().getMonth() + 1);
  const [includeBirthdays, setIncludeBirthdays] = useState(true);
  const [includeAnniversaries, setIncludeAnniversaries] = useState(true);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await api.list({ limit: 25, offset: 0, signal });
      setCampaigns(result.campaigns);
      setTotal(result.total);
      setLoadState('ready');
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      setLoadState('error');
    }
  }, [api]);

  useEffect(() => {
    const controller = new AbortController();
    void api.list({ limit: 25, offset: 0, signal: controller.signal })
      .then((result) => {
        setCampaigns(result.campaigns);
        setTotal(result.total);
        setLoadState('ready');
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setLoadState('error');
      });
    return () => controller.abort();
  }, [api]);

  async function createDraft() {
    if (!includeBirthdays && !includeAnniversaries) {
      setCreateError('Choose birthdays, home anniversaries, or both.');
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      const campaign = await api.createDraft({
        request_id: globalThis.crypto.randomUUID(),
        month,
        include_birthdays: includeBirthdays,
        include_home_anniversaries: includeAnniversaries,
      });
      router.push(`/admin/command/cards/${campaign.id}`);
    } catch {
      setCreateError('The review draft could not be prepared. Nothing was sent.');
      setCreating(false);
    }
  }

  const activeCount = useMemo(() => campaigns.filter((campaign) =>
    !['sent', 'failed'].includes(campaign.status)).length, [campaigns]);

  return (
    <div className="command-card-workspace min-h-[100dvh]">
      <CommandModuleHeader
        breadcrumbs={[{ label: 'Command', href: '/admin/command' }, { label: 'Cards' }]}
        title="Client cards"
        description="Source birthday and home-anniversary recipients from the reconciled Command archive, then review every card before approval."
        actions={(
          <button
            type="button"
            className="command-primary-button command-touch-target"
            onClick={() => setShowCreate((current) => !current)}
            aria-expanded={showCreate}
          >
            <Plus aria-hidden="true" size={18} />
            New campaign
          </button>
        )}
      />

      <main className="command-card-content command-content-gutters">
        <section className="command-card-hero" aria-labelledby="card-workflow-title">
          <div>
            <span className="command-card-eyebrow">CONTROLLED MAIL WORKFLOW</span>
            <h2 id="card-workflow-title">A human decision stays between Sydney and every mailbox.</h2>
            <p>
              Sydney can prepare the audience and copy. Brandon reviews the exact recipients and
              price here before any provider request is allowed.
            </p>
          </div>
          <div className="command-card-hero-proof" aria-label="Card workflow safeguards">
            <ShieldCheck aria-hidden="true" size={32} weight="duotone" />
            <strong>Approval locked</strong>
            <span>No automatic sending or unsafe retries.</span>
          </div>
        </section>

        <AnimatePresence initial={false}>
          {showCreate ? (
            <motion.section
              className="command-card-create"
              aria-labelledby="new-card-campaign-title"
              initial={reduceMotion ? false : { opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={reduceMotion ? { opacity: 0 } : { opacity: 0, height: 0 }}
              transition={spring}
            >
              <div className="command-card-create-heading">
                <CalendarDots aria-hidden="true" size={25} />
                <div>
                  <h2 id="new-card-campaign-title">Prepare a review draft</h2>
                  <p>This gathers contacts only. It does not approve or send cards.</p>
                </div>
              </div>
              <div className="command-card-create-fields">
                <label>
                  <span>Celebration month</span>
                  <select
                    value={month}
                    onChange={(event) => setMonth(Number(event.target.value))}
                    disabled={creating}
                  >
                    {monthNames.map((name, index) => (
                      <option key={name} value={index + 1}>{name}</option>
                    ))}
                  </select>
                </label>
                <fieldset>
                  <legend>Include</legend>
                  <label>
                    <input
                      type="checkbox"
                      checked={includeBirthdays}
                      onChange={(event) => setIncludeBirthdays(event.target.checked)}
                      disabled={creating}
                    />
                    Birthdays
                  </label>
                  <label>
                    <input
                      type="checkbox"
                      checked={includeAnniversaries}
                      onChange={(event) => setIncludeAnniversaries(event.target.checked)}
                      disabled={creating}
                    />
                    Home anniversaries
                  </label>
                </fieldset>
                <button
                  type="button"
                  className="command-primary-button command-touch-target"
                  onClick={() => void createDraft()}
                  disabled={creating}
                >
                  <CardsThree aria-hidden="true" size={19} />
                  {creating ? 'Building draft…' : 'Build review draft'}
                </button>
              </div>
              {createError ? <p className="command-card-inline-error" role="alert">{createError}</p> : null}
            </motion.section>
          ) : null}
        </AnimatePresence>

        <div className="command-card-section-heading">
          <div>
            <span>CAMPAIGN DESK</span>
            <h2>Recent review drafts</h2>
          </div>
          <p>{activeCount} active · {total} total</p>
        </div>

        {loadState === 'loading' ? (
          <CommandStatePanel
            kind="loading"
            title="Loading card campaigns"
            message="Checking the authoritative campaign ledger."
          />
        ) : loadState === 'error' ? (
          <CommandStatePanel
            kind="error"
            title="Card campaigns are unavailable"
            message="The review ledger could not be loaded. No card action was taken."
            actionLabel="Try again"
            onAction={() => {
              setLoadState('loading');
              void load();
            }}
          />
        ) : campaigns.length === 0 ? (
          <CommandStatePanel
            kind="first_run"
            title="No card campaigns yet"
            message="Prepare a draft to review this month's birthdays and home anniversaries."
            actionLabel="Prepare a campaign"
            onAction={() => setShowCreate(true)}
          />
        ) : (
          <div className="command-card-campaign-grid">
            <AnimatePresence>
              {campaigns.map((campaign) => (
                <CampaignCard key={campaign.id} campaign={campaign} />
              ))}
            </AnimatePresence>
          </div>
        )}
      </main>
    </div>
  );
}
