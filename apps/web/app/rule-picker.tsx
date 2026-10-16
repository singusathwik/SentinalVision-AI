'use client';

type Rule = { id: string; name?: string; kind?: string };

export function RulePicker({ rules, selected, onChange }: {
  rules: Rule[]; selected: string[]; onChange: (ids: string[]) => void;
}) {
  const renderRule = (rule: Rule) => <label className="rule-option" key={rule.id}>
    <input type="checkbox" checked={selected.includes(rule.id)} onChange={event => onChange(event.target.checked ? [...selected, rule.id] : selected.filter(id => id !== rule.id))} />
    <span className="rule-option-copy"><span className="rule-option-name">{rule.name || 'Unnamed rule'}</span><span className="rule-option-meta">{rule.kind === 'intrusion' ? 'Flag a person entering the marked area' : (rule.kind || 'Custom alert').replaceAll('_', ' ')}</span></span>
    {/^DEMO\b/i.test(rule.name || '') && <span className="badge">Sample</span>}
  </label>;
  return <section className="rule-picker" aria-labelledby="rule-picker-heading">
    <div className="row between"><h2 id="rule-picker-heading">Optional alerts</h2><span className="muted">{selected.length} selected</span></div>
    <p className="muted">Leave these unchecked to simply find people and show their tracking numbers. Select an alert only when its marked area matches your video.</p>
    {selected.length > 0 && <button type="button" onClick={() => onChange([])}>Clear selection</button>}
    <div className="rule-options">{rules.map(renderRule)}</div>
    {!rules.length && <p className="muted">To flag people entering an area, draw that area in Zone editor first.</p>}
  </section>;
}
