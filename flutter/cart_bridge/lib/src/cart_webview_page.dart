import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:webview_flutter/webview_flutter.dart';

import 'models.dart';

/// Full-screen WebView that opens the store's add-to-cart link.
///
/// The user can then:
///  * log in right here and check out, or
///  * tap "Open in app" to hand the cart over to the store's app / browser.
class CartWebViewPage extends StatefulWidget {
  /// Creates the page for the add-to-cart link [cartUrl].
  const CartWebViewPage({
    super.key,
    required this.cartUrl,
    this.store = CartStore.walmart,
    this.unmatched = const [],
    this.userAgent,
    this.title,
  });

  /// From [CartResult.cartUrl].
  final String cartUrl;

  /// The store the cart belongs to; used for labels and the refresh target.
  final CartStore store;

  /// Shown in a banner so the user knows what wasn't added.
  final List<UnmatchedIngredient> unmatched;

  /// Override if the store blocks the default WebView user agent.
  final String? userAgent;

  /// Overrides the app bar title.
  final String? title;

  @override
  State<CartWebViewPage> createState() => _CartWebViewPageState();
}

class _CartWebViewPageState extends State<CartWebViewPage> {
  late final WebViewController _controller;
  int _progress = 0;
  bool _showUnmatched = true;

  @override
  void initState() {
    super.initState();
    _controller = WebViewController()
      ..setJavaScriptMode(JavaScriptMode.unrestricted)
      ..setNavigationDelegate(
        NavigationDelegate(
          onProgress: (p) {
            if (mounted) setState(() => _progress = p);
          },
          onNavigationRequest: (req) {
            final uri = Uri.tryParse(req.url);
            if (uri == null) return NavigationDecision.prevent;
            if (uri.scheme == 'http' ||
                uri.scheme == 'https' ||
                uri.scheme == 'about') {
              return NavigationDecision.navigate;
            }
            // intent://, walmart://, tel:, mailto: ... -> hand to the OS.
            launchUrl(uri, mode: LaunchMode.externalApplication);
            return NavigationDecision.prevent;
          },
        ),
      );
    if (widget.userAgent != null) _controller.setUserAgent(widget.userAgent);
    _controller.loadRequest(Uri.parse(widget.cartUrl));
  }

  Future<void> _openInStoreApp() async {
    // Opening the add-to-cart link outside the WebView lets the store app (via
    // universal / app links) or the default browser add the same items to the
    // cart there. If the app isn't installed, it falls back to the browser.
    final ok = await launchUrl(Uri.parse(widget.cartUrl),
        mode: LaunchMode.externalApplication);
    if (!ok && mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('Could not open ${widget.store.displayName}')));
    }
  }

  Future<void> _refresh() async {
    // Reload the plain cart page, never the add-to-cart link (that would add items again).
    await _controller.loadRequest(Uri.parse(widget.store.cartPageUrl));
  }

  Future<bool> _handleBack() async {
    if (await _controller.canGoBack()) {
      await _controller.goBack();
      return false;
    }
    return true;
  }

  @override
  Widget build(BuildContext context) {
    final name = widget.store.displayName;
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) async {
        if (didPop) return;
        if (await _handleBack() && context.mounted) Navigator.of(context).pop();
      },
      child: Scaffold(
        appBar: AppBar(
          title: Text(widget.title ?? '$name cart'),
          leading: IconButton(
              icon: const Icon(Icons.close),
              onPressed: () => Navigator.of(context).pop()),
          actions: [
            IconButton(
                tooltip: 'Refresh cart',
                icon: const Icon(Icons.refresh),
                onPressed: _refresh)
          ],
          bottom: _progress < 100
              ? PreferredSize(
                  preferredSize: const Size.fromHeight(2),
                  child: LinearProgressIndicator(
                      value: _progress / 100, minHeight: 2),
                )
              : null,
        ),
        body: Column(
          children: [
            if (_showUnmatched && widget.unmatched.isNotEmpty)
              MaterialBanner(
                content: Text(
                  'Not added: ${widget.unmatched.map((u) => u.ingredient.name).join(', ')}',
                  maxLines: 3,
                  overflow: TextOverflow.ellipsis,
                ),
                actions: [
                  TextButton(
                      onPressed: () => setState(() => _showUnmatched = false),
                      child: const Text('OK'))
                ],
              ),
            Expanded(child: WebViewWidget(controller: _controller)),
          ],
        ),
        bottomNavigationBar: SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    'Log in here to check out, or continue in the $name app.',
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
                ),
                const SizedBox(width: 12),
                FilledButton.icon(
                  onPressed: _openInStoreApp,
                  icon: const Icon(Icons.open_in_new, size: 18),
                  label: const Text('Open in app'),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
