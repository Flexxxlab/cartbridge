import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

/// Thrown when a CartBridge request fails (network error, timeout, or an
/// HTTP error response from the server).
class CartBridgeException implements Exception {
  /// Creates an exception with a human-readable [message] and, when the server
  /// responded, its HTTP [statusCode].
  CartBridgeException(this.message, {this.statusCode});

  /// A human-readable description of what went wrong.
  final String message;

  /// The HTTP status code, or `null` for network errors and timeouts.
  final int? statusCode;

  /// Whether the server rejected the API key (HTTP 401).
  bool get isUnauthorized => statusCode == 401;

  /// Whether the account has no store credentials yet (HTTP 403). Add your
  /// Walmart credentials in the CartBridge dashboard.
  bool get isMissingStoreCredentials => statusCode == 403;

  /// Whether a rate limit was hit (HTTP 429). [message] says how long to wait.
  bool get isRateLimited => statusCode == 429;

  @override
  String toString() => 'CartBridgeException(${statusCode ?? '-'}): $message';
}

/// Thin HTTP client for the CartBridge service.
class CartBridgeClient {
  /// The hosted CartBridge service.
  static const defaultBaseUrl = 'https://cartbridge.flexxxlab.com';

  /// Creates a client authenticating with [apiKey] (from the CartBridge
  /// dashboard). [baseUrl] defaults to the hosted service; override it only for
  /// a self-hosted server or your own proxy. Pass [httpClient] to customize
  /// networking (e.g. in tests).
  CartBridgeClient({
    required this.apiKey,
    this.baseUrl = defaultBaseUrl,
    http.Client? httpClient,
    this.timeout = const Duration(seconds: 30),
  }) : _http = httpClient ?? http.Client();

  /// The bearer token sent with every request.
  final String apiKey;

  /// The CartBridge server, e.g. [defaultBaseUrl].
  final String baseUrl;

  /// How long to wait for the server before throwing a [CartBridgeException].
  final Duration timeout;
  final http.Client _http;

  Uri _uri(String path) =>
      Uri.parse('${baseUrl.replaceAll(RegExp(r'/+$'), '')}$path');

  Map<String, String> get _headers => {
        'Authorization': 'Bearer $apiKey',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      };

  /// Matches [items] to store products and returns a ready-to-open cart link.
  Future<CartResult> createCart({
    required List<Ingredient> items,
    CartStore store = CartStore.walmart,
  }) async {
    if (items.isEmpty) throw ArgumentError('items must not be empty');
    final body = jsonEncode(
        {'store': store.id, 'items': items.map((e) => e.toJson()).toList()});
    final res = await _send(
        () => _http.post(_uri('/v1/cart'), headers: _headers, body: body));
    return CartResult.fromJson(res as Map<String, dynamic>);
  }

  /// Useful to validate an API key.
  Future<Map<String, dynamic>> me() async =>
      (await _send(() => _http.get(_uri('/v1/me'), headers: _headers)))
          as Map<String, dynamic>;

  Future<dynamic> _send(Future<http.Response> Function() request) async {
    final http.Response res;
    try {
      res = await request().timeout(timeout);
    } on TimeoutException {
      throw CartBridgeException('Request timed out');
    } catch (e) {
      throw CartBridgeException('Network error: $e');
    }
    dynamic decoded;
    try {
      decoded =
          res.bodyBytes.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    } on FormatException {
      if (res.statusCode < 400) {
        throw CartBridgeException('Invalid JSON from server',
            statusCode: res.statusCode);
      }
    }
    if (res.statusCode >= 400) {
      final detail = decoded is Map ? decoded['detail'] : null;
      throw CartBridgeException(
          detail is String ? detail : 'HTTP ${res.statusCode}',
          statusCode: res.statusCode);
    }
    return decoded;
  }

  /// Releases the underlying HTTP client. Call when the client is no longer needed.
  void close() => _http.close();
}
