{{- define "pe.name" -}}{{ .Release.Name }}-api{{- end -}}

{{- define "pe.labels" -}}
app.kubernetes.io/name: pe-api
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: pe-platform
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}
