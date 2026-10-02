/**
 * Unit tests for the pure helpers: URL redaction must never leak query
 * values (sign, vk_user_id, tokens), whitelisting drops everything not
 * listed, and toErrorInfo preserves VK {error_type, error_data} shapes.
 */

import {
  collectMetrics,
  pickWhitelisted,
  redactUrl,
  toErrorInfo,
} from '../helpers';

describe('redactUrl', () => {
  it('keeps origin + path and parameter NAMES only', () => {
    const out = redactUrl(
      'https://vk.com/app123?vk_user_id=777777&sign=SECRET_SIGN_VALUE' +
        '&vk_platform=desktop_web&access_token=SECRET_TOKEN#hash_secret',
    );

    expect(out.url).toBe('https://vk.com/app123');
    expect(out.queryParams).toEqual([
      'vk_user_id',
      'sign',
      'vk_platform',
      'access_token',
    ]);

    const asText = JSON.stringify(out);
    for (const leaked of [
      '777777',
      'SECRET_SIGN_VALUE',
      'SECRET_TOKEN',
      'hash_secret',
    ]) {
      expect(asText).not.toContain(leaked);
    }
  });

  it('handles a bare URL and an unparseable string', () => {
    expect(redactUrl('https://example.com/path')).toEqual({
      url: 'https://example.com/path',
      queryParams: [],
    });
    expect(redactUrl('not a url')).toEqual({
      url: '<unparseable>',
      queryParams: [],
    });
  });
});

describe('pickWhitelisted', () => {
  it('keeps listed keys, drops everything else, fills absent with null', () => {
    const out = pickWhitelisted(
      {
        vk_app_id: 777,
        vk_platform: 'desktop_web',
        sign: 'SECRET_SIGN_VALUE',
        vk_user_id: 777777,
      },
      ['vk_app_id', 'vk_platform', 'vk_ref'],
    );

    expect(out).toEqual({
      vk_app_id: 777,
      vk_platform: 'desktop_web',
      vk_ref: null,
    });
    expect(JSON.stringify(out)).not.toContain('SECRET_SIGN_VALUE');
    expect('vk_user_id' in out).toBe(false);
    expect('sign' in out).toBe(false);
  });

  it('returns nulls for a non-object input', () => {
    expect(pickWhitelisted('oops', ['a', 'b'])).toEqual({
      a: null,
      b: null,
    });
  });
});

describe('toErrorInfo', () => {
  it('passes through Error name/message', () => {
    expect(toErrorInfo(new TypeError('boom'))).toEqual({
      name: 'TypeError',
      message: 'boom',
    });
  });

  it('preserves VK {error_type, error_data} verbatim', () => {
    const vkError = {
      error_type: 'client_error',
      error_data: { error_code: 1, error_reason: 'denied' },
    };
    expect(toErrorInfo(vkError)).toEqual({
      name: 'client_error',
      message: JSON.stringify(vkError.error_data),
      error_type: 'client_error',
      error_data: { error_code: 1, error_reason: 'denied' },
    });
  });

  it('normalises non-error primitives', () => {
    expect(toErrorInfo('nope')).toEqual({
      name: 'UnknownError',
      message: 'nope',
    });
  });
});

describe('collectMetrics', () => {
  it('reads the jsdom window/document without throwing', () => {
    const metrics = collectMetrics(window, document);
    expect(metrics.innerWidth).toBe(window.innerWidth);
    expect(metrics.isFramed).toBe(false);
    expect(metrics.userAgent).toBe(window.navigator.userAgent);
    expect(metrics.location.url).toBe(
      `${window.location.origin}${window.location.pathname}`,
    );
    // Absent browser APIs report null, not undefined/crash.
    expect(metrics.featurePolicyFullscreen).toBeNull();
    expect(metrics.permissionsPolicyFullscreen).toBeNull();
  });
});
