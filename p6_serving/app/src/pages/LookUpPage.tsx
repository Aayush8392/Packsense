import { useEffect, useId, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router';
import { PageTitle, TextPanel, pageSections } from '../components/pageParts';
import {
  CARD_DISCLAIMER, OFF_FLAGS_NOTE, SEED_NOTE, datesText, keyFieldsText, offFlagsText, offLink, rulesText, signalWords, statusNotice, versionsText,
} from '../data/cardWords';
import { lookupCard, resetCards, type Card, type Lookup } from '../data/cards';
import { checkDigitOk, cleanTyped, hasBarcodeLength, variants } from '../lookup/barcode';

type Outcome = { key: string; result: Lookup } | { key: string; failed: true };

function ExternalLink({ href, children }: { href: string; children: string }) {
  return (
    <a className="button button--quiet" href={href} target="_blank" rel="noopener noreferrer">
      {children}
      <span className="visually-hidden"> (opens in a new tab)</span>
    </a>
  );
}

function CardView({ card, typed }: { card: Card; typed: string }) {
  const notice = statusNotice(card.existence);
  const signal = signalWords(card.light);
  return (
    <article className="lookup-card" aria-label={`Card for barcode ${card.code}`}>
      <header className="lookup-card__head">
        <p className="lookup-card__code">Barcode: <span>{card.code}</span></p>
        <p className="lookup-card__tag">India slice: {card.inIndia ? 'Yes' : 'No'}</p>
      </header>
      {card.code !== typed && <p className="lookup-card__alias">Found under the stored form of the number you typed ({typed}).</p>}
      {notice ? (
        <div className="lookup-card__signal lookup-card__signal--notice">
          <p className="lookup-card__signal-label">{notice.title}</p>
          <p>{notice.body}</p>
        </div>
      ) : (
        <div className="lookup-card__signal">
          <p className="lookup-card__signal-label">{signal.label}</p>
          <p>{signal.line}</p>
        </div>
      )}
      {notice && !notice.replacesSignal && (
        <p className="lookup-card__signal-line"><strong>{signal.label}.</strong> {signal.line}</p>
      )}
      <dl className="lookup-card__facts">
        <div>
          <dt>Open Food Facts flags</dt>
          <dd>{offFlagsText(card)}<small>{OFF_FLAGS_NOTE}</small></dd>
        </div>
        <div>
          <dt>PackSense arithmetic checks</dt>
          <dd>{rulesText(card)}</dd>
        </div>
        <div>
          <dt>Key fields</dt>
          <dd>{keyFieldsText(card)}</dd>
        </div>
        <div>
          <dt>Versions</dt>
          <dd>{versionsText(card)}<small>{datesText(card)}</small>{card.firstPeriodFromSeed && <small>{SEED_NOTE}</small>}</dd>
        </div>
      </dl>
      <p className="lookup-card__action"><ExternalLink href={offLink(card.code)}>Open product on Open Food Facts</ExternalLink></p>
      <p className="lookup-card__disclaimer">{CARD_DISCLAIMER}</p>
    </article>
  );
}

function NotFound({ digits }: { digits: string }) {
  const checked = variants(digits).some(checkDigitOk);
  return (
    <div className="lookup-note">
      {!checked && (
        <p className="lookup-note__problem">
          <strong>The check digit does not add up.</strong> The last digit of a barcode is calculated from the others, and {digits} does not pass that calculation. Check the printed digits.
        </p>
      )}
      <p>
        <strong>Not in this copy.</strong> That does not mean the product is not on Open Food Facts.
      </p>
      <p><ExternalLink href={offLink(digits)}>Check directly on Open Food Facts</ExternalLink></p>
    </div>
  );
}

function BarcodeTool() {
  const [params, setParams] = useSearchParams();
  const fromAddress = params.get('barcode') ?? '';
  const [typed, setTyped] = useState(fromAddress);
  const [shownAddress, setShownAddress] = useState(fromAddress);
  const [problem, setProblem] = useState('');
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [attempt, setAttempt] = useState(0);
  const inputId = useId();
  const hintId = useId();
  const problemId = useId();

  // A new address (the Home box, a shared link, the back button) replaces what is in the box.
  if (shownAddress !== fromAddress) {
    setShownAddress(fromAddress);
    setTyped(fromAddress);
  }

  // The address holds the barcode, so the Home box, a shared link and the back button all land on a result.
  const cleaned = cleanTyped(fromAddress);
  const digits = cleaned !== null && hasBarcodeLength(cleaned) ? cleaned : null;
  const key = digits === null ? '' : `${digits}#${attempt}`;
  useEffect(() => {
    if (digits === null) return;
    let current = true;
    lookupCard(digits).then(
      (result) => current && setOutcome({ key, result }),
      () => current && setOutcome({ key, failed: true }),
    );
    return () => {
      current = false;
    };
  }, [digits, key]);
  const settled = digits !== null && outcome?.key === key ? outcome : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    const digits = cleanTyped(typed);
    if (digits === null) {
      setProblem('Enter digits only. Spaces and hyphens are fine; letters are not.');
      return;
    }
    if (!hasBarcodeLength(digits)) {
      setProblem('Enter 8 to 14 digits.');
      return;
    }
    setProblem('');
    const next = new URLSearchParams(params);
    next.set('barcode', digits);
    setParams(next, { state: { keepScroll: true } });
    setAttempt((n) => n + 1);
  }

  function retry() {
    resetCards();
    setAttempt((n) => n + 1);
  }

  return (
    <section className="lookup-tool" id="tool-barcode" aria-labelledby="barcode-heading">
      <h2 id="barcode-heading">Look up a barcode</h2>
      <form onSubmit={submit} noValidate>
        <label htmlFor={inputId}>Type the number under a barcode (8 to 14 digits)</label>
        <div className="lookup-tool__row">
          <input
            id={inputId}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            placeholder="e.g. 8901030383452"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            aria-describedby={`${hintId} ${problemId}`}
            aria-invalid={problem !== ''}
          />
          <button type="submit" className="button button--primary">Look up</button>
        </div>
        <p id={hintId} className="lookup-tool__hint">Spaces and hyphens are ignored. The address of this page holds the barcode, so a copy of the link shows the same card.</p>
        <p id={problemId} className="form-problem" role="alert">{problem}</p>
      </form>
      <div className="lookup-tool__result" aria-live="polite">
        {digits !== null && settled === null && <p className="data-loading">Looking in the card files…</p>}
        {digits !== null && settled && 'result' in settled && (settled.result.found ? <CardView card={settled.result.card} typed={digits} /> : <NotFound digits={digits} />)}
        {digits !== null && settled && 'failed' in settled && (
          <div className="lookup-note" role="alert">
            <p><strong>The card files could not be loaded just now.</strong> Check the connection and try again.</p>
            <p><button type="button" className="button button--quiet" onClick={retry}>Try again</button></p>
          </div>
        )}
      </div>
    </section>
  );
}

/** Look up: the privacy note, then the barcode tool and what its card shows. (The question tool is the chat button on every page.) */
export function LookUpPage() {
  const { intro, sections } = pageSections('barcode-lookup');
  const privacy = sections.find((s) => s.title === 'Your privacy');
  return (
    <div className="data-page lookup">
      <PageTitle slug="barcode-lookup" />
      {privacy && (
        <aside className="lookup-privacy" aria-labelledby="lookup-privacy-title">
          <h2 id="lookup-privacy-title">{privacy.title}</h2>
          <div className="prose" dangerouslySetInnerHTML={{ __html: privacy.html }} />
        </aside>
      )}
      <BarcodeTool />
      <TextPanel title="What the card shows" html={intro} id="lookup-card-shows" />
    </div>
  );
}
