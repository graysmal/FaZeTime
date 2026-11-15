// Runtime capability probe from the API's own /openapi.json. Optional operator features (evidence, a settle
// reason field, an AI-mode route, P4 candidates) are shown only when the running API actually has them.

export interface Capabilities {
  evidenceList: boolean;
  evidenceImage: boolean;
  /** Name of an optional free-text reason field on the settle body, if the API defines one. */
  settleReasonField: 'note' | 'reason' | null;
  aiModeRoute: string | null;
  candidateRoutes: string[];
  operatorPaths: string[];
}

type Json = Record<string, unknown>;

function isObj(v: unknown): v is Json {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function resolveRef(doc: Json, schema: unknown, depth = 0): Json | null {
  if (!isObj(schema) || depth > 4) return null;
  const ref = schema.$ref;
  if (typeof ref === 'string' && ref.startsWith('#/')) {
    let node: unknown = doc;
    for (const part of ref.slice(2).split('/')) node = isObj(node) ? node[part] : undefined;
    return resolveRef(doc, node, depth + 1);
  }
  return schema;
}

function bodyProperties(doc: Json, op: unknown): Set<string> {
  if (!isObj(op)) return new Set();
  const content = isObj(op.requestBody) ? op.requestBody.content : undefined;
  const json = isObj(content) ? content['application/json'] : undefined;
  const schema = resolveRef(doc, isObj(json) ? json.schema : undefined);
  const props = schema && isObj(schema.properties) ? Object.keys(schema.properties) : [];
  return new Set(props);
}

export function parseCapabilities(doc: unknown): Capabilities {
  const root = isObj(doc) ? doc : {};
  const paths = isObj(root.paths) ? root.paths : {};
  const names = Object.keys(paths);
  const has = (p: string, method: 'get' | 'post') => isObj(paths[p]) && isObj((paths[p] as Json)[method]);
  const settleOp = isObj(paths['/v1/operator/markets/{market_id}/settle'])
    ? (paths['/v1/operator/markets/{market_id}/settle'] as Json).post
    : undefined;
  const settleProps = bodyProperties(root, settleOp);
  const operatorPaths = names.filter((p) => p.startsWith('/v1/operator/')).sort();
  return {
    evidenceList: has('/v1/operator/evidence', 'get'),
    evidenceImage: has('/v1/operator/evidence/{evidence_id}', 'get'),
    settleReasonField: settleProps.has('note') ? 'note' : settleProps.has('reason') ? 'reason' : null,
    aiModeRoute: operatorPaths.find((p) => /ai[-_]?mode/i.test(p)) ?? null,
    candidateRoutes: operatorPaths.filter((p) => /proposal|candidate/i.test(p)),
    operatorPaths,
  };
}
