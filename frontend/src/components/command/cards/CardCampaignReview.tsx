'use client';

import Link from 'next/link';
import {
  ArrowClockwise,
  CalendarDots,
  CardsThree,
  Check,
  CheckCircle,
  ClockCountdown,
  EnvelopeOpen,
  FloppyDisk,
  HouseLine,
  LockKey,
  PaperPlaneTilt,
  ShieldCheck,
  WarningCircle,
} from '@phosphor-icons/react';
import { motion, useReducedMotion } from 'framer-motion';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  cardsApi,
  isCardCampaignConflict,
  type CardCampaignDetail,
  type CardCampaignStatus,
  type CardRecipient,
  type CardsApi,
} from '@/lib/command/cards';
import { CommandModuleHeader } from '../ui/CommandModuleHeader';
import { CommandOverlay } from '../ui/CommandOverlay';
import { CommandStatePanel } from '../ui/CommandStatePanel';

const spring = { type: 'spring' as const, stiffness: 100, damping: 20 };
const monthNames = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
] as const;

type LoadState = 'loading' | 'ready' | 'error';

export type CardCampaignReviewProps = Readonly<{
  campaignId: string;
  api?: CardsApi;
}>;

function money(cents: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
  }).format(cents / 100);
}

function celebrationLabel(recipient: CardRecipient): string {
  const occasion = recipient.celebration_kind === 'birthday'
    ? 'Birthday'
    : 'Home anniversary';
  return `${occasion} · ${monthNames[recipient.celebration_month - 1]} ${recipient.celebration_day}`;
}

function statusContent(status: CardCampaignStatus): Readonly<{
  title: string;
  message: string;
  tone: 'neutral' | 'success' | 'warning' | 'danger';
}> {
  const content: Readonly<Record<CardCampaignStatus, ReturnType<typeof statusContent>>> = {
    draft: {
      title: 'Draft needs review',
      message: 'Review recipients, mailing addresses, designs, and messages.',
      tone: 'neutral',
    },
    needs_addresses: {
      title: 'Mailing addresses need review',
      message: 'Open each missing contact or exclude that recipient before approval.',
      tone: 'warning',
    },
    needs_connection: {
      title: 'Provider connection required',
      message: 'The campaign is saved, but provider delivery remains locked.',
      tone: 'warning',
    },
    ready_for_review: {
      title: 'Ready for Brandon’s review',
      message: 'The exact audience and estimated cost can now be confirmed.',
      tone: 'neutral',
    },
    approved: {
      title: 'Approval recorded',
      message: 'The immutable approval is stored and delivery is being reconciled.',
      tone: 'neutral',
    },
    sending: {
      title: 'Sending is in progress',
      message: 'Do not repeat this request. The provider outcome is being reconciled.',
      tone: 'neutral',
    },
    sent: {
      title: 'Card order confirmed',
      message: 'The provider confirmed the approved recipient set.',
      tone: 'success',
    },
    partially_sent: {
      title: 'Some cards need attention',
      message: 'Confirmed and rejected recipients are shown below. Nothing will retry automatically.',
      tone: 'warning',
    },
    failed: {
      title: 'Card order was not completed',
      message: 'The failed attempt is preserved. A new send is locked pending manual review.',
      tone: 'danger',
    },
    delivery_uncertain: {
      title: 'Delivery outcome needs review',
      message: 'The provider result was ambiguous. Do not resend until it is reconciled manually.',
      tone: 'danger',
    },
  };
  return content[status];
}

function RecipientEditor({
  recipient,
  editable,
  busy,
  onSave,
}: Readonly<{
  recipient: CardRecipient;
  editable: boolean;
  busy: boolean;
  onSave: (input: Readonly<{
    message: string;
    designKey: string;
    excluded: boolean;
    exclusionReason?: string;
  }>) => Promise<void>;
}>) {
  const [message, setMessage] = useState(recipient.message);
  const [designKey, setDesignKey] = useState(recipient.design_key);
  const [excluded, setExcluded] = useState(recipient.excluded);
  const [exclusionReason, setExclusionReason] = useState(recipient.exclusion_reason ?? '');
  const [saving, setSaving] = useState(false);
  const [validation, setValidation] = useState<string | null>(null);
  const serverValues = useRef({
    message: recipient.message,
    designKey: recipient.design_key,
    excluded: recipient.excluded,
    exclusionReason: recipient.exclusion_reason ?? '',
  });

  useEffect(() => {
    const previous = serverValues.current;
    // Each editor is keyed by recipient ID. Merge only fields that still match
    // their prior server value so another tab cannot erase local draft edits.
    setMessage((current) => current === previous.message ? recipient.message : current);
    setDesignKey((current) => current === previous.designKey ? recipient.design_key : current);
    setExcluded((current) => current === previous.excluded ? recipient.excluded : current);
    setExclusionReason((current) => current === previous.exclusionReason
      ? recipient.exclusion_reason ?? '' : current);
    serverValues.current = {
      message: recipient.message,
      designKey: recipient.design_key,
      excluded: recipient.excluded,
      exclusionReason: recipient.exclusion_reason ?? '',
    };
  }, [recipient.message, recipient.design_key, recipient.excluded, recipient.exclusion_reason]);

  async function save() {
    if (message.trim().length === 0) {
      setValidation('Add a message before saving.');
      return;
    }
    if (excluded && exclusionReason.trim().length === 0) {
      setValidation('Add a reason for excluding this recipient.');
      return;
    }
    setValidation(null);
    setSaving(true);
    try {
      await onSave({
        message: message.trim(),
        designKey: designKey.trim(),
        excluded,
        ...(excluded ? { exclusionReason: exclusionReason.trim() } : {}),
      });
    } finally {
      setSaving(false);
    }
  }

  const outcomeLabel = recipient.delivery_outcome === 'confirmed'
    ? 'Confirmed sent'
    : recipient.delivery_outcome === 'rejected'
      ? 'Rejected by provider'
      : recipient.delivery_outcome === 'ambiguous'
        ? 'Outcome uncertain'
        : null;

  return (
    <motion.article
      layout
      className={`command-card-recipient${recipient.excluded ? ' is-excluded' : ''}`}
      aria-label={`Card for ${recipient.display_name}`}
      transition={spring}
    >
      <div className="command-card-recipient-heading">
        <div className="command-card-recipient-mark" aria-hidden="true">
          {recipient.celebration_kind === 'birthday'
            ? <CardsThree size={22} weight="duotone" />
            : <HouseLine size={22} weight="duotone" />}
        </div>
        <div>
          <span>{celebrationLabel(recipient)}</span>
          <h3>{recipient.display_name}</h3>
        </div>
        {outcomeLabel ? (
          <strong className={`command-card-delivery is-${recipient.delivery_outcome}`}>
            {outcomeLabel}
          </strong>
        ) : null}
      </div>

      <div className="command-card-address-row">
        {recipient.address_status === 'ready' ? (
          <>
            <CheckCircle aria-hidden="true" size={18} weight="fill" />
            <span>{recipient.address_summary}</span>
          </>
        ) : (
          <>
            <WarningCircle aria-hidden="true" size={18} weight="fill" />
            <span>Mailing address missing</span>
            <Link href={`/admin/command/contacts/${recipient.contact_id}`}>
              Open {recipient.display_name} contact
            </Link>
          </>
        )}
      </div>

      <label className="command-card-field">
        <span>Message for {recipient.display_name}</span>
        <textarea
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          rows={4}
          maxLength={2000}
          disabled={!editable || saving || busy}
        />
      </label>
      <label className="command-card-field">
        <span>Design key</span>
        <input
          value={designKey}
          onChange={(event) => setDesignKey(event.target.value)}
          maxLength={120}
          disabled={!editable || saving || busy}
        />
      </label>
      <label className="command-card-check">
        <input
          type="checkbox"
          checked={excluded}
          onChange={(event) => {
            setExcluded(event.target.checked);
            if (event.target.checked && exclusionReason === '' && recipient.address_status === 'missing') {
              setExclusionReason('Mailing address unavailable.');
            }
          }}
          disabled={!editable || saving || busy}
        />
        Exclude {recipient.display_name} from this campaign
      </label>
      {excluded ? (
        <label className="command-card-field">
          <span>Reason for excluding {recipient.display_name}</span>
          <input
            value={exclusionReason}
            onChange={(event) => setExclusionReason(event.target.value)}
            maxLength={500}
            disabled={!editable || saving || busy}
          />
        </label>
      ) : null}
      {validation ? <p className="command-card-inline-error" role="alert">{validation}</p> : null}
      {editable ? (
        <button
          type="button"
          className="command-secondary-button command-touch-target command-card-save"
          onClick={() => void save()}
          disabled={saving || busy}
        >
          <FloppyDisk aria-hidden="true" size={18} />
          {saving ? `Saving ${recipient.display_name}…` : `Save ${recipient.display_name} card`}
        </button>
      ) : null}
    </motion.article>
  );
}

export function CardCampaignReview({ campaignId, api = cardsApi }: CardCampaignReviewProps) {
  const reduceMotion = useReducedMotion();
  const [loadState, setLoadState] = useState<LoadState>('loading');
  const [campaign, setCampaign] = useState<CardCampaignDetail | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [alert, setAlert] = useState<string | null>(null);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [sending, setSending] = useState(false);
  const [refreshingAddresses, setRefreshingAddresses] = useState(false);
  const [savingRecipient, setSavingRecipient] = useState(false);
  const approveTriggerRef = useRef<HTMLButtonElement>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoadState('loading');
    try {
      const result = await api.get(campaignId, signal);
      setCampaign(result);
      setLoadState('ready');
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return;
      setLoadState('error');
    }
  }, [api, campaignId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function saveRecipient(
    recipient: CardRecipient,
    input: Readonly<{
      message: string;
      designKey: string;
      excluded: boolean;
      exclusionReason?: string;
    }>,
  ) {
    if (campaign === null || refreshingAddresses || savingRecipient || sending) return;
    setSavingRecipient(true);
    setNotice(null);
    setAlert(null);
    try {
      const updated = await api.update(campaignId, {
        expected_version: campaign.version,
        recipient_updates: [{
          recipient_id: recipient.id,
          message: input.message,
          design_key: input.designKey,
          excluded: input.excluded,
          ...(input.excluded ? { exclusion_reason: input.exclusionReason } : {}),
        }],
      });
      setCampaign(updated);
      setNotice(`${recipient.display_name} card saved`);
    } catch (error) {
      if (isCardCampaignConflict(error)) {
        setAlert('Campaign changed while you were reviewing it. Unsaved edits are kept; untouched fields show the latest version. Review before saving.');
        try {
          const authoritative = await api.get(campaignId);
          setCampaign(authoritative);
          setLoadState('ready');
        } catch {
          setLoadState('error');
        }
        return;
      }
      setAlert(`${recipient.display_name} card could not be saved. Nothing was sent.`);
    } finally {
      setSavingRecipient(false);
    }
  }

  async function refreshMissingAddresses() {
    if (campaign === null || refreshingAddresses || savingRecipient || sending) return;
    setRefreshingAddresses(true);
    setConfirmationOpen(false);
    setConfirmed(false);
    setNotice(null);
    setAlert(null);
    try {
      const updated = await api.update(campaignId, {
        expected_version: campaign.version,
        refresh_missing_addresses: true,
      });
      setCampaign(updated);
      setNotice('Mailing addresses checked. Review the draft before approving.');
    } catch (error) {
      if (isCardCampaignConflict(error)) {
        setAlert('Campaign changed while addresses were being checked. Unsaved edits are kept; untouched fields show the latest version. Review before saving.');
        try {
          const authoritative = await api.get(campaignId);
          setCampaign(authoritative);
          setLoadState('ready');
        } catch {
          setLoadState('error');
        }
        return;
      }
      setAlert('Mailing addresses could not be checked. Nothing was sent.');
    } finally {
      setRefreshingAddresses(false);
    }
  }

  async function approveAndSend() {
    if (campaign === null) return;
    const requestId = globalThis.crypto.randomUUID();
    setSending(true);
    setAlert(null);
    setNotice(null);
    try {
      const result = await api.approveAndSend(campaignId, {
        request_id: requestId,
        expected_version: campaign.version,
        confirmed_recipient_count: campaign.sendable_recipients,
        confirmed_cost_cents: campaign.estimated_cost_cents,
        confirmed_by_brandon: true,
      });
      setCampaign(result);
      setConfirmationOpen(false);
      setConfirmed(false);
    } catch {
      setConfirmationOpen(false);
      setConfirmed(false);
      try {
        const authoritative = await api.get(campaignId);
        setCampaign(authoritative);
        if (authoritative.send_request_id === requestId) {
          setNotice('The original send request was found in the campaign ledger.');
        } else {
          setAlert('The send outcome could not be confirmed. It was not retried automatically.');
        }
      } catch {
        setAlert('The send outcome could not be confirmed. It was not retried automatically.');
      }
    } finally {
      setSending(false);
    }
  }

  if (loadState === 'loading') {
    return (
      <div className="command-card-workspace min-h-[100dvh] command-content-gutters command-card-page-state">
        <CommandStatePanel
          kind="loading"
          title="Loading card campaign"
          message="Reading the authoritative audience and delivery ledger."
        />
      </div>
    );
  }

  if (loadState === 'error' || campaign === null) {
    return (
      <div className="command-card-workspace min-h-[100dvh] command-content-gutters command-card-page-state">
        <CommandStatePanel
          kind="error"
          title="Campaign is unavailable"
          message="The campaign could not be loaded. No card action was taken."
          actionLabel="Try again"
          onAction={() => void load()}
        />
      </div>
    );
  }

  const status = statusContent(campaign.status);
  const editable = ['draft', 'needs_addresses', 'needs_connection', 'ready_for_review']
    .includes(campaign.status);
  const canApprove = campaign.status === 'ready_for_review'
    && campaign.provider_connected
    && campaign.missing_address_count === 0
    && campaign.sendable_recipients > 0;

  return (
    <div className="command-card-workspace min-h-[100dvh]">
      <CommandModuleHeader
        breadcrumbs={[
          { label: 'Command', href: '/admin/command' },
          { label: 'Cards', href: '/admin/command/cards' },
          { label: campaign.title },
        ]}
        title={campaign.title}
        description={`${monthNames[campaign.month - 1]} birthdays and home anniversaries · version ${campaign.version}`}
        actions={canApprove ? (
          <button
            ref={approveTriggerRef}
            type="button"
            className="command-primary-button command-touch-target"
            onClick={() => setConfirmationOpen(true)}
            disabled={sending || refreshingAddresses || savingRecipient}
          >
            <PaperPlaneTilt aria-hidden="true" size={18} weight="fill" />
            Review and send
          </button>
        ) : null}
      />

      <main className="command-card-content command-content-gutters">
        {alert ? <div className="command-card-alert" role="alert"><WarningCircle aria-hidden="true" size={20} />{alert}</div> : null}
        {notice ? <div className="command-card-notice" role="status"><Check aria-hidden="true" size={20} />{notice}</div> : null}

        <motion.section
          className={`command-card-status-hero is-${status.tone}`}
          aria-labelledby="campaign-status-title"
          initial={reduceMotion ? false : { opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={spring}
        >
          <div className="command-card-status-icon" aria-hidden="true">
            {status.tone === 'success'
              ? <CheckCircle size={30} weight="duotone" />
              : status.tone === 'danger' || status.tone === 'warning'
                ? <WarningCircle size={30} weight="duotone" />
                : <ClockCountdown size={30} weight="duotone" />}
          </div>
          <div>
            <span>CAMPAIGN STATUS</span>
            <h2 id="campaign-status-title">{status.title}</h2>
            <p>{status.message}</p>
          </div>
          <div className="command-card-status-total">
            <strong>{campaign.sendable_recipients}</strong>
            <span>cards · {money(campaign.estimated_cost_cents)}</span>
          </div>
        </motion.section>

        <div className="command-card-review-grid">
          <section className="command-card-audience" aria-labelledby="campaign-audience-title">
            <div className="command-card-section-heading">
              <div>
                <span>LOCKED AUDIENCE</span>
                <h2 id="campaign-audience-title">Recipient review</h2>
              </div>
              <p>{campaign.total_recipients} sourced · {campaign.excluded_recipients} excluded</p>
            </div>
            <div className="command-card-recipient-list">
              {campaign.recipients.length > 0 ? campaign.recipients.map((recipient) => (
                <RecipientEditor
                  key={recipient.id}
                  recipient={recipient}
                  editable={editable}
                  busy={refreshingAddresses || savingRecipient || sending}
                  onSave={(input) => saveRecipient(recipient, input)}
                />
              )) : (
                <CommandStatePanel
                  kind="empty"
                  title="No matching celebrations"
                  message="The reconciled contact archive has no recipients for this campaign selection."
                />
              )}
            </div>
          </section>

          <aside className="command-card-review-rail" aria-label="Campaign readiness">
            <section>
              <div className="command-card-rail-heading">
                <ShieldCheck aria-hidden="true" size={22} />
                <h2>Approval gate</h2>
              </div>
              <dl>
                <div><dt>Ready recipients</dt><dd>{campaign.sendable_recipients}</dd></div>
                <div><dt>Missing addresses</dt><dd>{campaign.missing_address_count}</dd></div>
                <div><dt>Estimated cost</dt><dd>{money(campaign.estimated_cost_cents)}</dd></div>
                <div><dt>Provider</dt><dd>{campaign.provider_connected ? 'Connected' : 'Locked'}</dd></div>
              </dl>
            </section>

            {!campaign.provider_connected ? (
              <section className="command-card-blocker">
                <LockKey aria-hidden="true" size={24} weight="duotone" />
                <h2>Send Out Cards is not connected</h2>
                <p>
                  This campaign remains a review draft. Sending is safely locked until contracted
                  API access is configured and verified.
                </p>
                <a
                  className="command-secondary-button command-touch-target"
                  href="mailto:info@soldwithsweeney.com?subject=Send%20Out%20Cards%20provider%20setup"
                >
                  Request provider setup
                </a>
              </section>
            ) : null}

            {campaign.missing_address_count > 0 ? (
              <section className="command-card-blocker">
                <EnvelopeOpen aria-hidden="true" size={24} weight="duotone" />
                <h2>{campaign.missing_address_count} mailing address needed</h2>
                <p>Open the contact record to add an address, or explicitly exclude the recipient.</p>
              </section>
            ) : null}

            {editable && campaign.recipients.some((recipient) => recipient.address_status === 'missing') ? (
              <section className="command-card-blocker">
                <h2>Updated a contact’s address?</h2>
                <p>
                  Check for complete mailing addresses to fill missing entries in this draft.
                  Recipients, messages, and exclusions stay unchanged. Nothing is sent.
                </p>
                <button
                  type="button"
                  className="command-secondary-button command-touch-target"
                  onClick={() => void refreshMissingAddresses()}
                  disabled={refreshingAddresses || savingRecipient || sending}
                  aria-busy={refreshingAddresses}
                >
                  <ArrowClockwise aria-hidden="true" size={18} />
                  {refreshingAddresses ? 'Checking addresses…' : 'Check updated addresses'}
                </button>
              </section>
            ) : null}

            <section className="command-card-ledger-note">
              <CalendarDots aria-hidden="true" size={23} />
              <h2>Evidence preserved</h2>
              <p>
                Audience checksum <code>{campaign.audience_checksum.slice(0, 12)}</code> ties this
                review to the exact sourced contacts.
              </p>
            </section>
          </aside>
        </div>
      </main>

      <CommandOverlay
        open={confirmationOpen}
        onOpenChange={(open) => {
          if (sending) return;
          setConfirmationOpen(open);
          if (!open) setConfirmed(false);
        }}
        labelledBy="card-confirmation-title"
        closeLabel="Cancel card order"
        triggerRef={approveTriggerRef}
      >
        <div className="command-card-confirmation">
          <div className="command-card-confirmation-icon" aria-hidden="true">
            <PaperPlaneTilt size={28} weight="duotone" />
          </div>
          <span>FINAL APPROVAL</span>
          <h2 id="card-confirmation-title">Confirm card order</h2>
          <p>
            You are approving <strong>{campaign.sendable_recipients} cards</strong> at an estimated
            total of <strong>{money(campaign.estimated_cost_cents)}</strong>.
          </p>
          <p className="command-card-confirmation-warning">
            This creates one provider request. An uncertain result will never retry automatically.
          </p>
          <label className="command-card-check command-card-confirm-check">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
              disabled={sending}
            />
            I confirm {campaign.sendable_recipients} cards for {money(campaign.estimated_cost_cents)}
          </label>
          <div className="command-card-confirm-actions">
            <button
              type="button"
              className="command-secondary-button command-touch-target"
              onClick={() => setConfirmationOpen(false)}
              disabled={sending}
            >
              Cancel
            </button>
            <button
              type="button"
              className="command-primary-button command-touch-target"
              onClick={() => void approveAndSend()}
              disabled={!confirmed || sending}
            >
              {sending ? (
                <><ArrowClockwise className="command-state-spinner" aria-hidden="true" size={18} /> Sending once…</>
              ) : (
                <><PaperPlaneTilt aria-hidden="true" size={18} /> Confirm and send {campaign.sendable_recipients} cards</>
              )}
            </button>
          </div>
        </div>
      </CommandOverlay>
    </div>
  );
}
