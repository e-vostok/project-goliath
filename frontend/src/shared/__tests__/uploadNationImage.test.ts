/**
 * api.uploadNationImage (version 0.12.0 unit 6): PUT
 * /nations/me/images/{kind} sends the FILE ITSELF as the raw body —
 * Bearer header present, no JSON content type, no JSON serialization.
 */

import { Blob as NodeBlob } from 'node:buffer';
import { http, HttpResponse } from 'msw';

import { server } from '../../../vitest.setup';
import { api } from '../api-client';

describe('api.uploadNationImage', () => {
  it('sends the raw file body with Bearer and no JSON content type', async () => {
    // A node:buffer Blob — undici (msw's fetch) streams it per spec;
    // jsdom's File would be stringified, which is a test-env artifact.
    const file = new NodeBlob(['PNGDATA'], { type: 'image/png' }) as Blob;
    const seen: {
      auth: string | null;
      contentType: string | null;
      body: Blob | null;
    } = { auth: null, contentType: null, body: null };
    server.use(
      http.put('*/api/v1/nations/me/images/flag', async ({ request }) => {
        seen.auth = request.headers.get('authorization');
        seen.contentType = request.headers.get('content-type');
        seen.body = await request.blob();
        return HttpResponse.json({
          kind: 'flag',
          url: '/api/v1/images/aa/full',
          thumb_url: '/api/v1/images/aa/thumb',
        });
      }),
    );

    const res = await api.uploadNationImage('tok-1', 'flag', file);

    expect(seen.auth).toBe('Bearer tok-1');
    expect(seen.contentType).not.toBe('application/json');
    // The File itself is the body — not JSON, not multipart.
    expect(seen.body).toBeInstanceOf(Blob);
    expect(seen.body?.size).toBe(file.size);
    expect(res).toEqual({
      kind: 'flag',
      url: '/api/v1/images/aa/full',
      thumb_url: '/api/v1/images/aa/thumb',
    });
  });
});
