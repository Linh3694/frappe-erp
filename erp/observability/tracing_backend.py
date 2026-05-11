# Copyright (c) 2026, Wellspring ERP
"""Đăng ký TracerProvider + instrument requests outbound."""

from __future__ import annotations


def configure_otel(*, endpoint_hostport: str, service_name: str) -> None:
	"""Điểm cuối dạng host:port (gRPC không TLS, LAN)."""

	from opentelemetry import trace

	from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
	from opentelemetry.sdk.resources import Resource
	from opentelemetry.sdk.trace import TracerProvider
	from opentelemetry.sdk.trace.export import BatchSpanProcessor

	resource = Resource.create(
		{
			"service.name": service_name,
			"service.namespace": "wis",
		}
	)
	exporter = OTLPSpanExporter(endpoint=endpoint_hostport, insecure=True)
	provider = TracerProvider(resource=resource)
	provider.add_span_processor(BatchSpanProcessor(exporter))
	trace.set_tracer_provider(provider)

	try:
		from opentelemetry.instrumentation.requests import RequestsInstrumentor

		RequestsInstrumentor().instrument()
	except Exception:
		# không fail app nếu thiếu optional hook
		pass


def root_tracer():
	"""Tracer mặc định của service erp."""
	from opentelemetry import trace

	return trace.get_tracer("erp")
