/* Deterministic, area-preserving jogakbo composition and textile rendering. */
(function (root) {
  'use strict';

  const ELEMENTS = ['목', '화', '토', '금', '수'];
  const TEXTURE_VERSION = 'ramie-1';
  const STEM_ELEMENTS = { 갑: '목', 을: '목', 병: '화', 정: '화', 무: '토', 기: '토', 경: '금', 신: '금', 임: '수', 계: '수' };
  const FALLBACK_COLORS = { 목: '#A7BDA4', 화: '#DBA09A', 토: '#D3BF96', 금: '#E7E2D8', 수: '#A4B8C5' };
  const TOPIC_OFFSETS = { 비견: 0, 겁재: 0, 식신: 1, 상관: 1, 편재: 2, 정재: 2, 편관: 3, 정관: 3, 편인: 4, 정인: 4 };

  function seededRandom(seed) {
    let value = parseInt(seed.slice(0, 8), 16) || 1;
    return () => {
      value = (Math.imul(value, 1664525) + 1013904223) >>> 0;
      return value / 4294967296;
    };
  }

  function mix(source, target, amount) {
    const parts = [1, 3, 5].map((offset) => {
      const from = parseInt(source.slice(offset, offset + 2), 16);
      const to = parseInt(target.slice(offset, offset + 2), 16);
      return Math.round(from + (to - from) * amount).toString(16).padStart(2, '0');
    });
    return `#${parts.join('')}`;
  }

  function paletteForReport(report) {
    const palette = { ...FALLBACK_COLORS };
    const day = report.colors.find((color) => color.role === '고유색');
    const dayElement = STEM_ELEMENTS[day.basis];
    const dayIndex = ELEMENTS.indexOf(dayElement);
    // Priority: unique color, talent, relationship, then the balance color.
    // Several roles can refer to one element; keep one hue per element.
    const assigned = new Set();
    report.colors.flatMap(color => [color, color.companion].filter(Boolean)).forEach((color) => {
      const element = color.element || (color.role === '고유색' ? dayElement
        : color.role === '균형색' ? color.basis
          : ELEMENTS[(dayIndex + TOPIC_OFFSETS[color.basis]) % 5]);
      if (!assigned.has(element)) {
        palette[element] = color.hex;
        assigned.add(element);
      }
    });
    if (report.colors.some(color => color.companion)) {
      ELEMENTS.filter(element => !assigned.has(element)).forEach(element => {
        palette[element] = palette[nearestElement(element, [...assigned])];
      });
    }
    return palette;
  }

  function nearestElement(element, assigned) {
    const index = ELEMENTS.indexOf(element);
    const distance = candidate => {
      const gap = Math.abs(ELEMENTS.indexOf(candidate) - index);
      return Math.min(gap, 5 - gap);
    };
    return assigned.reduce((best, candidate) => distance(candidate) < distance(best) ? candidate : best);
  }

  function tonesForReport(report) {
    const palette = paletteForReport(report);
    const tones = Object.fromEntries(ELEMENTS.map(element => [element, []]));
    const day = report.colors.find(color => color.role === '고유색');
    const dayElement = STEM_ELEMENTS[day.basis];
    const dayIndex = ELEMENTS.indexOf(dayElement);
    const assigned = [];
    report.colors.flatMap(color => [color, color.companion].filter(Boolean)).forEach(color => {
      const element = color.element || (color.role === '고유색' ? dayElement : color.role === '균형색' ? color.basis
        : ELEMENTS[(dayIndex + TOPIC_OFFSETS[color.basis]) % 5]);
      if (!assigned.includes(element)) assigned.push(element);
      tones[element].push(color);
    });
    ELEMENTS.forEach(element => {
      if (!tones[element].length) {
        tones[element] = report.colors.some(color => color.companion)
          ? [...tones[nearestElement(element, assigned)]] : [{ hex: palette[element], role: '오행 기본색' }];
      }
    });
    return tones;
  }

  function bindingColorsForReport(report) {
    return report.expanded_colors || report.colors.flatMap(color => [color, color.companion].filter(Boolean));
  }

  function buildLayout(report) {
    const random = seededRandom(report.pattern_seed);
    const family = report.pattern_family?.key || 'weave';
    const pieces = [];
    const tones = tonesForReport(report);
    const total = ELEMENTS.reduce((sum, element) => sum + report.visual_composition[element], 0);
    if (total !== 6 && total !== 8) throw new Error('조각보는 6칸 또는 8칸 구성이 필요합니다.');
    ELEMENTS.forEach((element) => {
      const count = report.visual_composition[element];
      if (!count) return;
      const partCount = Math.max(2, tones[element].length, count * (family === 'quiet' ? 2 : 3));
      const weights = Array.from({ length: partCount }, () => .28 + random() * 1.35);
      const sum = weights.reduce((value, weight) => value + weight, 0);
      weights.forEach((weight) => pieces.push({ element, weight: (count / total) * (weight / sum) }));
    });
    for (let index = pieces.length - 1; index > 0; index -= 1) {
      const other = Math.floor(random() * (index + 1));
      [pieces[index], pieces[other]] = [pieces[other], pieces[index]];
    }
    const layout = [];
    function split(items, x, y, width, height, depth) {
      if (items.length === 1) {
        layout.push({ ...items[0], x, y, width, height, grain: random(), shade: random() });
        return;
      }
      const cut = Math.max(1, Math.min(items.length - 1, Math.round(items.length * (.32 + random() * .36))));
      const left = items.slice(0, cut);
      const right = items.slice(cut);
      const leftWeight = left.reduce((sum, item) => sum + item.weight, 0);
      const fullWeight = items.reduce((sum, item) => sum + item.weight, 0);
      const ratio = leftWeight / fullWeight;
      const aspect = family === 'ribbon' ? .8 : family === 'window' ? 1.3 : 1;
      let vertical = width / height > aspect;
      if (width / height > .7 && width / height < 1.5 && random() > .57) vertical = !vertical;
      if (depth === 0 && family === 'courtyard') vertical = false;
      if (vertical) {
        split(left, x, y, width * ratio, height, depth + 1);
        split(right, x + width * ratio, y, width * (1 - ratio), height, depth + 1);
      } else {
        split(left, x, y, width, height * ratio, depth + 1);
        split(right, x, y + height * ratio, width, height * (1 - ratio), depth + 1);
      }
    }
    split(pieces, 0, 0, 1, 1, 0);
    return layout;
  }

  function coloredLayout(report) {
    const tones = tonesForReport(report);
    const next = Object.fromEntries(ELEMENTS.map(element => [element, 0]));
    return buildLayout(report).map(piece => {
      const color = tones[piece.element][next[piece.element]++ % tones[piece.element].length];
      return { ...piece, hex: color.hex, colorRole: color.role, variant: color.variant || 'primary' };
    });
  }

  function lightnessShade(hex, change) {
    const [r, g, b] = [1, 3, 5].map(index => parseInt(hex.slice(index, index + 2), 16) / 255);
    const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
    const lightness = (max + min) / 2;
    const saturation = delta ? delta / (1 - Math.abs(2 * lightness - 1)) : 0;
    const hue = !delta ? 0 : max === r ? ((g - b) / delta + 6) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
    return `hsl(${hue * 60} ${saturation * 100}% ${Math.min(.97, Math.max(.03, lightness + change)) * 100}%)`;
  }

  function drawFabric(context, rectangle, color, random) {
    const { x, y, width, height, grain, shade } = rectangle;
    context.save();
    context.beginPath();
    context.rect(x, y, width, height);
    context.clip();
    const silk = context.createLinearGradient(x, y, x + width, y + height);
    silk.addColorStop(0, lightnessShade(color, .04 + shade * .02));
    silk.addColorStop(.4, color);
    silk.addColorStop(1, lightnessShade(color, -.055));
    context.fillStyle = silk;
    context.fillRect(x, y, width, height);

    // Backlit ramie: irregular thread spacing/thickness, tiny open pores and
    // alternating over-under intersections. Everything is clipped to the patch.
    const warp = [], weft = [];
    for (let offset = 1; offset < width; offset += 3.4 + random() * 1.9) warp.push(offset);
    for (let offset = 2; offset < height; offset += 4.1 + random() * 2.1) weft.push(offset);
    context.fillStyle = lightnessShade(color, .105);
    warp.forEach((offset, index) => {
      if (index % 2) return;
      weft.forEach((cross, row) => {
        if ((index + row) % 3 === 0) context.fillRect(x + offset + 1.3, y + cross + 1.2, 1.1, 1.5);
      });
    });
    warp.forEach((offset) => {
      const thickness = .55 + random() * .8;
      const bend = (random() - .5) * 1.4;
      context.beginPath();
      context.moveTo(x + offset, y);
      context.bezierCurveTo(x + offset + bend, y + height / 3, x + offset - bend, y + height * .7, x + offset, y + height);
      context.strokeStyle = lightnessShade(color, -.055);
      context.lineWidth = thickness + .65;
      context.globalAlpha = .4;
      context.stroke();
      context.strokeStyle = lightnessShade(color, .12);
      context.lineWidth = thickness;
      context.globalAlpha = .62;
      context.stroke();
    });
    weft.forEach((offset, row) => {
      context.beginPath();
      context.moveTo(x, y + offset);
      context.bezierCurveTo(x + width / 3, y + offset + .65, x + width * .7, y + offset - .6, x + width, y + offset);
      context.strokeStyle = lightnessShade(color, row % 2 ? .10 : -.055);
      context.globalAlpha = row % 2 ? .58 : .3;
      context.lineWidth = .55 + random() * .75;
      context.stroke();
    });
    // Short raised slubs and fine, soft fibers distinguish cloth from a grid.
    context.globalAlpha = 1;
    for (let index = 0; index < Math.ceil(width * height / 550); index += 1) {
      const fiberX = x + random() * width;
      const fiberY = y + random() * height;
      const vertical = random() > .3;
      const length = 3 + random() * 12;
      context.beginPath();
      context.moveTo(fiberX, fiberY);
      context.lineTo(fiberX + (vertical ? .4 : length), fiberY + (vertical ? length : .4));
      context.strokeStyle = lightnessShade(color, .13);
      context.globalAlpha = .2 + random() * .23;
      context.lineWidth = .7 + random() * .6;
      context.stroke();
    }
    context.globalAlpha = 1;
    for (let index = 0; index < 16; index += 1) {
      const fiberX = x + random() * width;
      const fiberY = y + random() * height;
      context.beginPath();
      context.moveTo(fiberX, fiberY);
      context.lineTo(fiberX + (grain > .5 ? 30 : 1), fiberY + (grain > .5 ? 1 : 30));
      context.strokeStyle = 'rgba(255,255,255,.16)';
      context.lineWidth = 1;
      context.stroke();
    }

    // Folded seam: a translucent overlap, a shadow, and two fine stitch rows.
    const folded = context.createLinearGradient(x, y, x + 10, y + 10);
    folded.addColorStop(0, 'rgba(47,32,23,.21)');
    folded.addColorStop(.65, 'rgba(47,32,23,.075)');
    folded.addColorStop(1, 'rgba(47,32,23,0)');
    context.fillStyle = folded;
    context.fillRect(x, y, 10, height);
    context.fillRect(x, y, width, 9);
    context.strokeStyle = 'rgba(255,250,233,.64)';
    context.lineWidth = 1.2;
    context.strokeRect(x + 4, y + 4, Math.max(0, width - 8), Math.max(0, height - 8));
    context.setLineDash([3.2, 4.2]);
    context.strokeStyle = 'rgba(255,251,235,.45)';
    context.lineWidth = .9;
    context.strokeRect(x + 8, y + 8, Math.max(0, width - 16), Math.max(0, height - 16));
    context.restore();
  }

  function draw(canvas, report) {
    const context = canvas.getContext('2d');
    const palette = paletteForReport(report);
    const layout = coloredLayout(report);
    const random = seededRandom(report.pattern_seed.slice(8) + report.pattern_seed.slice(0, 8));
    const byRole = Object.fromEntries(report.colors.map((color) => [color.role, color]));
    const { width, height } = canvas;
    const unit = width / 1600;
    context.clearRect(0, 0, width, height);
    context.save();
    context.scale(unit, unit);
    const paper = context.createLinearGradient(0, 0, 1600, 2000);
    paper.addColorStop(0, '#fffcf6');
    paper.addColorStop(1, mix(byRole['균형색'].hex, '#fffaf1', .9));
    context.fillStyle = paper;
    context.fillRect(0, 0, 1600, height / unit);

    context.fillStyle = '#91734f';
    context.font = '500 26px Arial, sans-serif';
    context.fillText('MaC   /   CHROMATIC ATELIER', 120, 104);
    context.textAlign = 'right';
    context.fillStyle = '#8c8071';
    context.font = '24px Georgia, serif';
    context.fillText('Astral Color', 1480, 104);
    context.textAlign = 'left';
    context.fillStyle = '#37342e';
    context.font = '500 62px Pretendard, Arial, sans-serif';
    context.fillText('나의 색을 잇다', 120, 205);
    context.fillStyle = '#857a6d';
    context.font = '26px Pretendard, Arial, sans-serif';
    context.fillText('조각마다 담긴 나의 흐름, 한 장의 보자기로', 122, 255);

    const artX = 120;
    const artY = 326;
    const artSize = 1360;
    const binding = 28;
    const innerSize = artSize - binding * 2;
    context.save();
    context.shadowColor = 'rgba(79,58,39,.19)';
    context.shadowBlur = 32;
    context.shadowOffsetY = 14;
    context.fillStyle = byRole['관계색'].hex;
    context.fillRect(artX, artY, artSize, artSize);
    context.restore();
    // The binding and surrounding paper are outside the proportional patch area.
    const bindingColors = bindingColorsForReport(report);
    // All eight tones remain in the artwork even if an element has zero area.
    bindingColors.forEach((color, index) => {
      const side = Math.floor(index * 4 / bindingColors.length);
      const perSide = bindingColors.length / 4;
      const offset = (index % perSide) * artSize / perSide;
      const length = artSize / perSide;
      const rectangle = side === 0 ? { x: artX + offset, y: artY, width: length, height: binding }
        : side === 1 ? { x: artX + artSize - binding, y: artY + offset, width: binding, height: length }
        : side === 2 ? { x: artX + artSize - offset - length, y: artY + artSize - binding, width: length, height: binding }
        : { x: artX, y: artY + artSize - offset - length, width: binding, height: length };
      drawFabric(context, { ...rectangle, grain: .5, shade: .5 }, color.hex, random);
    });
    layout.forEach((piece) => drawFabric(context, {
      ...piece,
      x: artX + binding + piece.x * innerSize,
      y: artY + binding + piece.y * innerSize,
      width: piece.width * innerSize,
      height: piece.height * innerSize,
    }, piece.hex, random));

    context.save();
    context.beginPath();
    context.rect(artX, artY, artSize, artSize);
    context.clip();
    const daylight = context.createRadialGradient(artX + 230, artY + 110, 20, artX + 400, artY + 330, artSize);
    daylight.addColorStop(0, 'rgba(255,250,230,.18)');
    daylight.addColorStop(.5, 'rgba(255,250,230,.035)');
    daylight.addColorStop(1, 'rgba(255,250,230,0)');
    context.fillStyle = daylight;
    context.fillRect(artX, artY, artSize, artSize);
    // Soft diagonal fabric creases, kept subtle so the color stays legible.
    for (let index = 0; index < 3; index += 1) {
      const start = artY + 230 + index * 360 + random() * 100;
      context.beginPath();
      context.moveTo(artX, start);
      context.bezierCurveTo(artX + 360, start - 50, artX + 1000, start + 60, artX + artSize, start + 20);
      context.strokeStyle = 'rgba(255,252,236,.09)';
      context.lineWidth = 18;
      context.stroke();
      context.strokeStyle = 'rgba(58,39,24,.025)';
      context.lineWidth = 3;
      context.stroke();
    }
    context.restore();
    context.save();
    context.setLineDash([4, 5]);
    context.strokeStyle = 'rgba(255,247,221,.64)';
    context.lineWidth = 1.5;
    context.strokeRect(artX + 9, artY + 9, artSize - 18, artSize - 18);
    context.restore();

    context.fillStyle = '#6f6354';
    context.font = '27px Pretendard, Arial, sans-serif';
    context.fillText(report.pattern_family?.name || '나만의 조각보', 120, 1752);
    context.textAlign = 'right';
    context.fillStyle = '#9a8a75';
    context.font = '23px Georgia, serif';
    context.fillText(`No. ${report.pattern_seed.slice(0, 8).toUpperCase()}`, 1480, 1752);
    context.textAlign = 'left';
    report.colors.forEach((color, index) => {
      const x = 120 + index * 342;
      context.fillStyle = color.hex;
      context.fillRect(x, 1810, 42, 42);
      context.strokeStyle = 'rgba(61,46,30,.12)';
      context.lineWidth = 1;
      context.strokeRect(x, 1810, 42, 42);
      context.fillStyle = '#7e7161';
      context.font = '21px Pretendard, Arial, sans-serif';
      context.fillText(color.display_role || (color.role === '균형색' ? '보완색' : color.role), x + 56, 1828);
      context.fillStyle = '#3d3933';
      context.font = '23px Pretendard, Arial, sans-serif';
      context.fillText(color.name, x + 56, 1859, 265);
      if (color.companion) {
        context.fillStyle = color.companion.hex;
        context.fillRect(x, 1880, 32, 32);
        context.fillStyle = '#6f6354';
        context.font = '20px Pretendard, Arial, sans-serif';
        context.fillText(`${color.companion.name}  ${color.companion.hex}`, x + 45, 1903);
      }
    });
    context.fillStyle = '#897a68';
    context.font = '22px Pretendard, Arial, sans-serif';
    const ratios = ELEMENTS.map((element) => `${element} ${Math.round(report.visual_composition[element] / report.visual_slot_count * 1000) / 10}%`).join('   ·   ');
    context.fillText(`패치 면적  /  ${ratios}`, 120, 1958);
    context.restore();
    return { layout, palette, bindingColors, textureVersion: TEXTURE_VERSION };
  }

  const api = { ELEMENTS, TEXTURE_VERSION, paletteForReport, tonesForReport, bindingColorsForReport, buildLayout, coloredLayout, draw };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.AstralJogakbo = api;
}(typeof globalThis !== 'undefined' ? globalThis : this));
