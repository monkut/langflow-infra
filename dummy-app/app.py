#!/usr/bin/env python3
"""
Minimal placeholder HTTP server for AWS Fargate initial deployment.
No external dependencies - uses only Python standard library.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import os


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler that responds to health checks"""

    def do_GET(self):
        """Handle GET requests"""
        # Health check endpoints for ALB
        if self.path in ['/', '/health/', '/admin/login/']:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()

            response = {
                'status': 'healthy',
                'service': 'placeholder-app',
                'message': 'This is a placeholder application. Deploy your real application to replace this.',
                'path': self.path
            }
            self.wfile.write(json.dumps(response).encode())
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'error': 'Not found'}).encode())

    def log_message(self, format, *args):
        """Log to stdout for CloudWatch"""
        print(f"{self.address_string()} - {format % args}")


def main():
    """Run the HTTP server"""
    port = int(os.getenv('PORT', '8000'))
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"Placeholder app listening on port {port}...")
    httpd.serve_forever()


if __name__ == '__main__':
    main()
