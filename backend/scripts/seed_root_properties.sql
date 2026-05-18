-- Seed root property definitions from kök.pdf
-- Root node: f03df925-f4c7-4466-8fe5-f662e09f2a25

BEGIN;

-- 1. Remove yaml_instance_property_values that reference root-defined properties (RESTRICT FK)
WITH RECURSIVE subtree AS (
  SELECT id FROM property_definitions
  WHERE defined_at_curriculum_node_id = 'f03df925-f4c7-4466-8fe5-f662e09f2a25'
  UNION ALL
  SELECT pd.id FROM property_definitions pd
  JOIN subtree s ON pd.parent_property_id = s.id
)
DELETE FROM yaml_instance_property_values
WHERE property_definition_id IN (SELECT id FROM subtree);

-- 2. Delete all root-defined properties (CASCADE removes children + overrides)
DELETE FROM property_definitions
WHERE defined_at_curriculum_node_id = 'f03df925-f4c7-4466-8fe5-f662e09f2a25';

-- 3. Insert new properties
-- Ordering: parents before children

INSERT INTO property_definitions
  (id, defined_at_curriculum_node_id, parent_property_id, label, description,
   property_key, canonical_path, data_type, default_value, constraints_json,
   is_required, is_active, created_at, updated_at)
VALUES

-- ── 1. Meta ─────────────────────────────────────────────────────────────────
('pd2-meta', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', NULL,
 'Meta', NULL, 'meta', 'meta', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-meta-id', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-meta',
 'Id', NULL, 'id', 'meta.id', 'text', NULL, NULL, false, true, NOW(), NOW()),

('pd2-meta-ad', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-meta',
 'Ad', NULL, 'ad', 'meta.ad', 'text', NULL, NULL, false, true, NOW(), NOW()),

('pd2-meta-aciklama', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-meta',
 'Açıklama', NULL, 'aciklama', 'meta.aciklama', 'text', NULL, NULL, false, true, NOW(), NOW()),

-- ── 2. Format ────────────────────────────────────────────────────────────────
('pd2-format', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', NULL,
 'Format', NULL, 'format', 'format', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-duzen', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format',
 'Düzen', NULL, 'duzen', 'format.duzen', 'enum', NULL, NULL, false, true, NOW(), NOW()),

-- 2b. Ek bilgi
('pd2-format-ek-bilgi', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format',
 'Ek Bilgi', NULL, 'ek_bilgi', 'format.ek_bilgi', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-ek-bilgi-required', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-ek-bilgi',
 'Required', NULL, 'required', 'format.ek_bilgi.required', 'bool', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-ek-bilgi-kurallar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-ek-bilgi',
 'Kurallar', NULL, 'kurallar', 'format.ek_bilgi.kurallar', 'array', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-ek-bilgi-yasaklar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-ek-bilgi',
 'Yasaklar', NULL, 'yasaklar', 'format.ek_bilgi.yasaklar', 'array', NULL, NULL, false, true, NOW(), NOW()),

-- 2c. Öncül
('pd2-format-oncul', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format',
 'Öncül', NULL, 'oncul', 'format.oncul', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-oncul-required', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-oncul',
 'Required', NULL, 'required', 'format.oncul.required', 'bool', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-oncul-kurallar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-oncul',
 'Kurallar', NULL, 'kurallar', 'format.oncul.kurallar', 'array', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-oncul-yasaklar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-oncul',
 'Yasaklar', NULL, 'yasaklar', 'format.oncul.yasaklar', 'array', NULL, NULL, false, true, NOW(), NOW()),

-- 2d. Paragraf
('pd2-format-paragraf', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format',
 'Paragraf', NULL, 'paragraf', 'format.paragraf', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-paragraf-required', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-paragraf',
 'Required', NULL, 'required', 'format.paragraf.required', 'bool', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-paragraf-kurallar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-paragraf',
 'Kurallar', NULL, 'kurallar', 'format.paragraf.kurallar', 'array', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-paragraf-yasaklar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-paragraf',
 'Yasaklar', NULL, 'yasaklar', 'format.paragraf.yasaklar', 'array', NULL, NULL, false, true, NOW(), NOW()),

-- 2d-iv. Word count
('pd2-format-paragraf-word-count', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-paragraf',
 'Word Count', NULL, 'word_count', 'format.paragraf.word_count', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-paragraf-word-count-min', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-paragraf-word-count',
 'Min', NULL, 'min', 'format.paragraf.word_count.min', 'number', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-paragraf-word-count-max', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-paragraf-word-count',
 'Max', NULL, 'max', 'format.paragraf.word_count.max', 'number', NULL, NULL, false, true, NOW(), NOW()),

-- 2d-v. Sentence count
('pd2-format-paragraf-sentence-count', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-paragraf',
 'Sentence Count', NULL, 'sentence_count', 'format.paragraf.sentence_count', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-paragraf-sentence-count-min', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-paragraf-sentence-count',
 'Min', NULL, 'min', 'format.paragraf.sentence_count.min', 'number', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-paragraf-sentence-count-max', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-paragraf-sentence-count',
 'Max', NULL, 'max', 'format.paragraf.sentence_count.max', 'number', NULL, NULL, false, true, NOW(), NOW()),

-- 2e. Soru kökü
('pd2-format-soru-koku', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format',
 'Soru Kökü', NULL, 'soru_koku', 'format.soru_koku', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-soru-koku-kurallar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-soru-koku',
 'Kurallar', NULL, 'kurallar', 'format.soru_koku.kurallar', 'array', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-soru-koku-yasaklar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-soru-koku',
 'Yasaklar', NULL, 'yasaklar', 'format.soru_koku.yasaklar', 'array', NULL, NULL, false, true, NOW(), NOW()),

-- 2f. Seçenekler
('pd2-format-secenekler', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format',
 'Seçenekler', NULL, 'secenekler', 'format.secenekler', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-secenekler-kurallar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-secenekler',
 'Kurallar', NULL, 'kurallar', 'format.secenekler.kurallar', 'array', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-secenekler-yasaklar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-secenekler',
 'Yasaklar', NULL, 'yasaklar', 'format.secenekler.yasaklar', 'array', NULL, NULL, false, true, NOW(), NOW()),

-- 2f-iii. Seçenekler > Görsel
('pd2-format-secenekler-gorsel', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-secenekler',
 'Görsel', NULL, 'gorsel', 'format.secenekler.gorsel', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-secenekler-gorsel-required', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-secenekler-gorsel',
 'Required', NULL, 'required', 'format.secenekler.gorsel.required', 'bool', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-secenekler-gorsel-kurallar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-secenekler-gorsel',
 'Kurallar', NULL, 'kurallar', 'format.secenekler.gorsel.kurallar', 'array', NULL, NULL, false, true, NOW(), NOW()),

('pd2-format-secenekler-gorsel-yasaklar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-format-secenekler-gorsel',
 'Yasaklar', NULL, 'yasaklar', 'format.secenekler.gorsel.yasaklar', 'array', NULL, NULL, false, true, NOW(), NOW()),

-- ── 3. Doğru cevap ───────────────────────────────────────────────────────────
('pd2-dogru-cevap', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', NULL,
 'Doğru Cevap', NULL, 'dogru_cevap', 'dogru_cevap', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-dogru-cevap-tanim', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-dogru-cevap',
 'Tanım', NULL, 'tanim', 'dogru_cevap.tanim', 'text', NULL, NULL, false, true, NOW(), NOW()),

('pd2-dogru-cevap-kurallar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-dogru-cevap',
 'Kurallar', NULL, 'kurallar', 'dogru_cevap.kurallar', 'array', NULL, NULL, false, true, NOW(), NOW()),

('pd2-dogru-cevap-yasaklar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-dogru-cevap',
 'Yasaklar', NULL, 'yasaklar', 'dogru_cevap.yasaklar', 'array', NULL, NULL, false, true, NOW(), NOW()),

-- ── 4. Çeldiriciler ──────────────────────────────────────────────────────────
('pd2-celdiriciler', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', NULL,
 'Çeldiriciler', NULL, 'celdiriciler', 'celdiriciler', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-celdiriciler-kurallar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-celdiriciler',
 'Kurallar', NULL, 'kurallar', 'celdiriciler.kurallar', 'array', NULL, NULL, false, true, NOW(), NOW()),

('pd2-celdiriciler-yasaklar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-celdiriciler',
 'Yasaklar', NULL, 'yasaklar', 'celdiriciler.yasaklar', 'array', NULL, NULL, false, true, NOW(), NOW()),

-- ── 5. Zorluk seviyesi ───────────────────────────────────────────────────────
('pd2-zorluk-seviyesi', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', NULL,
 'Zorluk Seviyesi', NULL, 'zorluk_seviyesi', 'zorluk_seviyesi', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-zorluk-seviyesi-zorluk', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-zorluk-seviyesi',
 'Zorluk', NULL, 'zorluk', 'zorluk_seviyesi.zorluk', 'enum', NULL, NULL, false, true, NOW(), NOW()),

('pd2-zorluk-seviyesi-kurallar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-zorluk-seviyesi',
 'Kurallar', NULL, 'kurallar', 'zorluk_seviyesi.kurallar', 'array', NULL, NULL, false, true, NOW(), NOW()),

-- ── 6. Ana görsel ────────────────────────────────────────────────────────────
('pd2-ana-gorsel', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', NULL,
 'Ana Görsel', NULL, 'ana_gorsel', 'ana_gorsel', 'object', NULL, NULL, false, true, NOW(), NOW()),

('pd2-ana-gorsel-kurallar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-ana-gorsel',
 'Kurallar', NULL, 'kurallar', 'ana_gorsel.kurallar', 'array', NULL, NULL, false, true, NOW(), NOW()),

('pd2-ana-gorsel-yasaklar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-ana-gorsel',
 'Yasaklar', NULL, 'yasaklar', 'ana_gorsel.yasaklar', 'array', NULL, NULL, false, true, NOW(), NOW()),

('pd2-ana-gorsel-stil', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', 'pd2-ana-gorsel',
 'Stil', NULL, 'stil', 'ana_gorsel.stil', 'text', NULL, NULL, false, true, NOW(), NOW()),

-- ── 7. Doğrulamalar ──────────────────────────────────────────────────────────
('pd2-dogrulamalar', 'f03df925-f4c7-4466-8fe5-f662e09f2a25', NULL,
 'Doğrulamalar', NULL, 'dogrulamalar', 'dogrulamalar', 'object', NULL, NULL, false, true, NOW(), NOW());

COMMIT;
