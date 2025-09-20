import { useEffect, useRef } from 'react';
import * as d3 from 'd3';

const POSITION_ORDER = ['FWD', 'MID', 'DEF', 'GKP'];
const PITCH_COLOR = '#14532d';
const LINE_COLOR = 'rgba(226, 232, 240, 0.75)';

function buildPlayerCoordinates(starters, pitch) {
  const grouped = d3.group(starters, (player) => player.position || 'MID');
  const coords = [];

  POSITION_ORDER.forEach((position, index) => {
    const rowPlayers = grouped.get(position) || [];
    if (!rowPlayers.length) return;

    const y = pitch.top + pitch.height * ([0.12, 0.38, 0.64, 0.88][index] ?? 0.5);
    const spacing = pitch.width / (rowPlayers.length + 1);

    rowPlayers
      .slice()
      .sort((a, b) => (b.value ?? 0) - (a.value ?? 0))
      .forEach((player, idx) => {
        coords.push({
          ...player,
          x: pitch.left + spacing * (idx + 1),
          y,
        });
      });
  });

  return coords;
}

function drawPitch(svg, pitch) {
  const { left, top, width, height } = pitch;

  svg
    .append('rect')
    .attr('x', left)
    .attr('y', top)
    .attr('width', width)
    .attr('height', height)
    .attr('rx', 24)
    .attr('fill', PITCH_COLOR)
    .attr('stroke', LINE_COLOR)
    .attr('stroke-width', 2);

  svg
    .append('line')
    .attr('x1', left)
    .attr('x2', left + width)
    .attr('y1', top + height / 2)
    .attr('y2', top + height / 2)
    .attr('stroke', LINE_COLOR)
    .attr('stroke-width', 1.5)
    .attr('stroke-dasharray', '6 6');

  svg
    .append('circle')
    .attr('cx', left + width / 2)
    .attr('cy', top + height / 2)
    .attr('r', 60)
    .attr('fill', 'none')
    .attr('stroke', LINE_COLOR)
    .attr('stroke-width', 1.2)
    .attr('stroke-dasharray', '6 6');

  const boxWidth = width * 0.55;
  const boxHeight = height * 0.18;
  const sixY = height * 0.08;

  svg
    .append('rect')
    .attr('x', left + (width - boxWidth) / 2)
    .attr('width', boxWidth)
    .attr('y', top)
    .attr('height', boxHeight)
    .attr('fill', 'none')
    .attr('stroke', LINE_COLOR)
    .attr('stroke-width', 1.2);

  svg
    .append('rect')
    .attr('x', left + (width - boxWidth) / 2)
    .attr('width', boxWidth)
    .attr('y', top + height - boxHeight)
    .attr('height', boxHeight)
    .attr('fill', 'none')
    .attr('stroke', LINE_COLOR)
    .attr('stroke-width', 1.2);

  const sixWidth = width * 0.35;
  svg
    .append('rect')
    .attr('x', left + (width - sixWidth) / 2)
    .attr('width', sixWidth)
    .attr('y', top)
    .attr('height', sixY)
    .attr('fill', 'none')
    .attr('stroke', LINE_COLOR)
    .attr('stroke-width', 1);

  svg
    .append('rect')
    .attr('x', left + (width - sixWidth) / 2)
    .attr('width', sixWidth)
    .attr('y', top + height - sixY)
    .attr('height', sixY)
    .attr('fill', 'none')
    .attr('stroke', LINE_COLOR)
    .attr('stroke-width', 1);
}

export default function FormationChart({ data }) {
  const { starters = [], bench = [] } = data ?? {};
  const containerRef = useRef(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const svgWidth = 780;
    const svgHeight = 560;
    const pitch = {
      left: 70,
      right: svgWidth - 70,
      top: 40,
      bottom: svgHeight - 180,
    };
    pitch.width = pitch.right - pitch.left;
    pitch.height = pitch.bottom - pitch.top;

    const root = d3.select(container);
    root.selectAll('*').remove();

    const svg = root
      .append('svg')
      .attr('viewBox', `0 0 ${svgWidth} ${svgHeight}`)
      .attr('class', 'formation-svg');

    drawPitch(svg, pitch);

    const coordinates = buildPlayerCoordinates(starters, pitch);
    const formatValue = d3.format('.2f');

    const playersGroup = svg.append('g').attr('class', 'players-layer');

    const playerNodes = playersGroup
      .selectAll('g.player')
      .data(coordinates, (d) => d.id || d.name)
      .join('g')
      .attr('class', 'player')
      .attr('transform', (d) => `translate(${d.x}, ${d.y})`);

    playerNodes
      .append('circle')
      .attr('r', 28)
      .attr('fill', '#1d4ed8')
      .attr('stroke', (d) => (d.is_captain ? '#facc15' : '#e2e8f0'))
      .attr('stroke-width', (d) => (d.is_captain ? 4 : d.is_vice ? 2.5 : 1.5))
      .attr('opacity', 0.9);

    playerNodes
      .append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '0.35em')
      .attr('fill', '#f8fafc')
      .attr('font-size', 12)
      .attr('font-weight', 600)
      .text((d) => (d.name || '?').split(' ')[0]);

    playerNodes
      .append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', 42)
      .attr('fill', '#f8fafc')
      .attr('font-size', 12)
      .text((d) => `${d.name}${d.is_captain ? ' (C)' : d.is_vice ? ' (V)' : ''}`);

    playerNodes
      .append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', 58)
      .attr('fill', '#94a3b8')
      .attr('font-size', 11)
      .text((d) =>
        d.value !== undefined && d.value !== null ? `${formatValue(d.value)} pts` : ''
      );

    if (bench.length) {
      const benchTop = pitch.bottom + 50;
      const benchGroup = svg
        .append('g')
        .attr('class', 'bench-layer')
        .attr('transform', `translate(${pitch.left}, ${benchTop})`);

      benchGroup
        .append('text')
        .attr('x', 0)
        .attr('y', -24)
        .attr('fill', '#94a3b8')
        .attr('font-size', 13)
        .text('Bench');

      const benchSpacing = pitch.width / Math.max(bench.length + 1, 2);
      const benchNodes = benchGroup
        .selectAll('g.bench-player')
        .data(bench, (d) => d.id || d.name)
        .join('g')
        .attr('class', 'bench-player')
        .attr('transform', (d, idx) => `translate(${benchSpacing * (idx + 1) - 60}, 0)`);

      benchNodes
        .append('rect')
        .attr('width', 120)
        .attr('height', 58)
        .attr('rx', 10)
        .attr('fill', '#0f172a')
        .attr('stroke', '#1e293b');

      benchNodes
        .append('text')
        .attr('x', 60)
        .attr('y', 20)
        .attr('text-anchor', 'middle')
        .attr('fill', '#e2e8f0')
        .attr('font-size', 12)
        .text((d) => d.name || '');

      benchNodes
        .append('text')
        .attr('x', 60)
        .attr('y', 38)
        .attr('text-anchor', 'middle')
        .attr('fill', '#94a3b8')
        .attr('font-size', 11)
        .text((d) => (d.value !== undefined ? `${formatValue(d.value)} pts` : d.position));
    }
  }, [starters, bench]);

  return <div className="formation-container" ref={containerRef} />;
}
