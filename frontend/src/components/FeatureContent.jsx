import BarChart from './BarChart.jsx';
import FormationChart from './FormationChart.jsx';

function toNumeric(value) {
  if (value == null) return NaN;
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : NaN;
  }

  const cleaned = String(value)
    .replace(/,/g, '')
    .replace(/[^0-9.\-]/g, '');

  const parsed = Number.parseFloat(cleaned);
  return Number.isFinite(parsed) ? parsed : NaN;
}

function extractSeriesFromTable(result) {
  const headers = Array.isArray(result.headers) ? result.headers : [];
  const rows = Array.isArray(result.rows) ? result.rows : [];
  if (!rows.length || !headers.length) {
    return { series: [] };
  }

  const labelIndex = 0;
  const candidateColumns = headers.map((_, columnIndex) => {
    let numericCount = 0;
    let total = 0;
    rows.forEach((row) => {
      const value = toNumeric(row[columnIndex]);
      if (Number.isFinite(value)) {
        numericCount += 1;
        total += value;
      }
    });
    return {
      index: columnIndex,
      ratio: numericCount / rows.length,
      average: numericCount ? total / numericCount : 0
    };
  });

  const bestColumn = candidateColumns
    .filter((candidate) => candidate.index !== labelIndex && candidate.ratio >= 0.6)
    .sort((a, b) => b.ratio - a.ratio || b.average - a.average)[0];

  if (!bestColumn) {
    return { series: [] };
  }

  const series = rows
    .map((row) => {
      const label = row[labelIndex] ?? '';
      const rawValue = row[bestColumn.index];
      const value = toNumeric(rawValue);
      if (!Number.isFinite(value)) {
        return null;
      }
      return {
        label: String(label),
        value,
        displayValue: typeof rawValue === 'string' ? rawValue : undefined
      };
    })
    .filter(Boolean)
    .slice(0, 25);

  return {
    series,
    valueLabel: headers[bestColumn.index]
  };
}

function deriveSeriesFromResult(result) {
  if (Array.isArray(result.chartSeries) && result.chartSeries.length) {
    return {
      series: result.chartSeries,
      valueLabel: result.chartLabel || result.valueLabel || '',
    };
  }
  return extractSeriesFromTable(result);
}

function parseTextResult(text) {
  if (!text) return [];

  const cleanText = text.replace(/\r\n?/g, '\n');
  const rawBlocks = cleanText.split(/\n\s*\n/).map((block) => block.trim()).filter(Boolean);

  return rawBlocks.map((block) => {
    const lines = block.split('\n').map((line) => line.trim()).filter(Boolean);
    if (lines.length === 0) return null;

    const section = {
      title: '',
      keyValues: [],
      bullets: [],
      paragraphs: []
    };

    const headingPattern = /^-+\s*(.*?)\s*-+$/;
    const allCapsPattern = /^[A-Z][A-Z\s\/&]+$/;

    let contentLines = lines;

    const firstLine = lines[0];
    const headingMatch = firstLine.match(headingPattern);
    if (headingMatch && headingMatch[1].trim().length > 0) {
      section.title = headingMatch[1].trim();
      contentLines = lines.slice(1);
    } else if (allCapsPattern.test(firstLine) && lines.length > 1) {
      section.title = firstLine;
      contentLines = lines.slice(1);
    }

    contentLines.forEach((line) => {
      if (!line) return;

      const bulletMatch = line.match(/^(?:[-•]|\*)\s+(.*)$/);
      if (bulletMatch) {
        section.bullets.push(bulletMatch[1]);
        return;
      }

      const kvMatch = line.match(/^([^:]+):\s*(.*)$/);
      if (kvMatch && kvMatch[1].length < 40) {
        section.keyValues.push({ label: kvMatch[1].trim(), value: kvMatch[2].trim() });
        return;
      }

      section.paragraphs.push(line);
    });

    return section;
  }).filter(Boolean);
}

export default function FeatureContent({ result, loading }) {
  if (loading) {
    return (
      <div className="content-placeholder">
        <p>Fetching data, please wait…</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="content-placeholder">
        <p>Select a feature from the sidebar to get started.</p>
      </div>
    );
  }

  if (result.error) {
    return (
      <div className="content-placeholder error">
        <p>{result.error}</p>
      </div>
    );
  }

  if (result.type === 'team') {
    const starters = result.starters ?? [];
    const bench = result.bench ?? [];
    const formation = result.formation || '';
    const metadata = result.metadata ?? {};

    return (
      <div className="team-visual">
        <div className="team-header">
          {result.title ? <h2>{result.title}</h2> : null}
          <div className="team-meta">
            {formation ? <span className="team-badge">Formation: {formation}</span> : null}
            {metadata.total_points !== undefined ? (
              <span className="team-badge">Total Points: {metadata.total_points}</span>
            ) : null}
            {metadata.total_predicted_score !== undefined ? (
              <span className="team-badge">Predicted Score: {metadata.total_predicted_score}</span>
            ) : null}
            {metadata.total_players ? (
              <span className="team-badge">Squad Size: {metadata.total_players}</span>
            ) : null}
          </div>
        </div>
        <FormationChart data={{ starters, bench }} />
      </div>
    );
  }

  if (result.type === 'table') {
    const { series, valueLabel } = deriveSeriesFromResult(result);
    const metadataBadges = [];
    if (result.metadata?.gameweek) {
      metadataBadges.push(`GW ${result.metadata.gameweek}`);
    }
    if (result.metadata?.league_name) {
      metadataBadges.push(result.metadata.league_name);
    }
    if (result.metadata?.predicted_total !== undefined) {
      const total = Number(result.metadata.predicted_total);
      if (Number.isFinite(total)) {
        metadataBadges.push(`Predicted Total: ${total.toFixed(2)}`);
      }
    }
    const recommendation = result.metadata?.recommendation;

    return (
      <div className="content-table">
        {result.title ? <h2>{result.title}</h2> : null}
        {metadataBadges.length ? (
          <div className="table-meta">
            {metadataBadges.map((badge) => (
              <span className="table-badge" key={badge}>
                {badge}
              </span>
            ))}
          </div>
        ) : null}
        {series.length ? (
          <div className="chart-panel">
            <h3>Quick Glance</h3>
            <BarChart data={series} valueLabel={valueLabel} />
          </div>
        ) : null}
        <div className="table-wrapper">
          <table>
            <thead>
              <tr>
                {result.headers?.map((header) => (
                  <th key={header}>{header}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {result.rows?.map((row, rowIndex) => (
                <tr key={`${rowIndex}-${row[0]}`}>
                  {row.map((cell, cellIndex) => (
                    <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {recommendation ? (
          <div className="table-note">{recommendation}</div>
        ) : null}
        {result.metadata?.note ? (
          <div className="table-note">{result.metadata.note}</div>
        ) : null}
      </div>
    );
  }

  const textContent = result.data ?? result.content ?? '';
  const sections = parseTextResult(textContent);

  if (sections.length === 0) {
    return (
      <div className="content-text">
        <pre>{textContent}</pre>
      </div>
    );
  }

  return (
    <div className="content-grid">
      {sections.map((section, index) => (
        <article className="section-card" key={`${section.title}-${index}`}>
          {section.title ? <h3>{section.title}</h3> : null}

          {section.keyValues.length > 0 ? (
            <dl className="key-value-grid">
              {section.keyValues.map(({ label, value }) => (
                <div key={`${label}-${value}`} className="key-value-item">
                  <dt>{label}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          ) : null}

          {section.bullets.length > 0 ? (
            <ul className="section-list">
              {section.bullets.map((bullet, idx) => (
                <li key={idx}>{bullet}</li>
              ))}
            </ul>
          ) : null}

          {section.paragraphs.length > 0 ? (
            <div className="section-paragraphs">
              {section.paragraphs.map((paragraph, idx) => (
                <p key={idx}>{paragraph}</p>
              ))}
            </div>
          ) : null}
        </article>
      ))}
    </div>
  );
}
