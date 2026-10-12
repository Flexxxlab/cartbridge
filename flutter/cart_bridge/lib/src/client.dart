import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

class CartBridgeException implements Exception {
  CartBridgeException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  bool get isUnauthorized => statusCode == 401;

  @override
  String toString() => 'CartBridgeException(${statusCode ?? '-'}): $message';
}

/// Thin HTTP client for the CartBridge backend.
class CartBridgeClient {
  CartBridgeClient({
    required this.apiKey,
    required this.baseUrl,
    http.Client? httpClient,
    this.timeout = const Duration(seconds: 30),
  }) : _http = httpClient ?? http.Client();

  final String apiKey;

  /// e.g. https://api.yourdomain.com
  final String baseUrl;
  final Duration timeout;
  final http.Client _http;

  Uri _uri(String path) => Uri.parse('${baseUrl.replaceAll(RegExp(r'/+$'), '')}$path');

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
    final body = jsonEncode({'store': store.id, 'items': items.map((e) => e.toJson()).toList()});
    final res = await _send(() => _http.post(_uri('/v1/cart'), headers: _headers, body: body));
    return CartResult.fromJson(res as Map<String, dynamic>);
  }

  /// Useful to validate an API key.
  Future<Map<String, dynamic>> me() async =>
      (await _send(() => _http.get(_uri('/v1/me'), headers: _headers))) as Map<String, dynamic>;

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
      decoded = res.bodyBytes.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    } on FormatException {
      if (res.statusCode < 400) throw CartBridgeException('Invalid JSON from server', statusCode: res.statusCode);
    }
    if (res.statusCode >= 400) {
      final detail = decoded is Map ? decoded['detail'] : null;
      throw CartBridgeException(detail is String ? detail : 'HTTP ${res.statusCode}', statusCode: res.statusCode);
    }
    return decoded;
  }

  void close() => _http.close();
}
