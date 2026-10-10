"""Promote a completed run using existing verified/model caches; never invoke inference."""

import argparse
import asyncio
import json

import httpx

from app.claims.snippet_analysis import analyze_snippets
from app.claims.source_analysis_input import analysis_input, verification_input
from app.config import Settings
from app.core.analysis_cache import AnalysisCache
from app.reporting.reliability_report import (
    ReliabilityResponse,
    generate_report,
    input_digest,
    report_evidence,
)


class CacheOnly:
    batch_snippets = True
    require_claim_focus = True
    similarity_target = 'other_documents'

    async def chat(self, payload):
        raise RuntimeError('Cache promotion stopped: an inference response is not cached.')

    async def embed(self, payload):
        raise RuntimeError('Cache promotion stopped: an embedding response is not cached.')

    async def unload(self, model):
        pass


async def promote(run_id):
    settings = Settings()
    data = settings.database.parent

    def load(folder):
        return json.loads((data / folder / f'{run_id}.json').read_text(encoding='utf-8'))

    collection, original = load('collections'), load('source-analyses')
    if collection.get('status') != 'completed':
        raise ValueError('Only a completed collection can be promoted.')
    response = ReliabilityResponse.model_validate(load('reliability-results'))
    packet = report_evidence(collection, original, response, input_digest(original))
    with httpx.Client(base_url=settings.ollama_url, trust_env=False) as http:
        tags = http.get('/api/tags')
        tags.raise_for_status()
        models = {item['name']: item for item in tags.json()['models']}

    def digest(name):
        item = models[name if ':' in name else name + ':latest']
        if item.get('remote_host') or item.get('remote_model'):
            raise ValueError('A downloaded local model is required.')
        return item['digest']

    client = CacheOnly()
    client.force_cpu = settings.ollama_force_cpu
    client.cache = AnalysisCache(data / 'analysis-cache', digest(settings.ollama_model))
    client.embedding_cache = AnalysisCache(data / 'embedding-cache', digest(settings.ollama_embedding_model))
    question, documents = analysis_input(collection)
    replay = await analyze_snippets(client, question, documents, settings.ollama_model,
                                   settings.ollama_embedding_model)
    if verification_input(replay) != verification_input(original):
        raise ValueError('Cache replay differs from the original verification input.')
    report = await generate_report(client, settings.ollama_model, packet, [])
    print(json.dumps({'run_id': run_id, 'verification_unchanged': True,
                      'analysis': replay['timings'], 'report': report['timings']}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id')
    args = parser.parse_args()
    if len(args.run_id) != 32 or any(c not in '0123456789abcdef' for c in args.run_id):
        parser.error('run_id must be the 32-character hexadecimal scenario ID.')
    asyncio.run(promote(args.run_id))


if __name__ == '__main__':
    main()
