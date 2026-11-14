# Decisión de IA para la demo

Fecha de consulta: 14 de noviembre de 2026. **Decisión v1:** usar **Gemini Developer API en su nivel gratuito**, invocado desde una función de Google Cloud, para proponer una hipótesis y pasos de verificación cuando nace un incidente colectivo. Los umbrales, estados y prioridades siguen siendo deterministas. El operador revisa la sugerencia. La arquitectura está en [arquitectura-solucion-v1.md](arquitectura-solucion-v1.md).

## Comparación de opciones gratuitas

| Nube / servicio | Condición gratuita verificada en fuente oficial | Aporte posible a Red TeleCorp | Decisión |
| --- | --- | --- | --- |
| **Google: Gemini Developer API** | Tiene nivel gratuito con acceso limitado a ciertos modelos y cuota de entrada/salida gratuita. El contenido del nivel gratuito puede usarse para mejorar productos de Google; límites y modelos concretos se consultan en el proyecto. [Precios de Gemini API](https://ai.google.dev/gemini-api/docs/pricing), [facturación](https://ai.google.dev/gemini-api/docs/billing). | Recibe hechos de un incidente y pocos casos históricos similares de BigQuery; produce una hipótesis y una lista breve de verificaciones con referencias a los eventos de origen. | **Preferida para prototipo con datos ficticios o depurados.** Cloud Run es el componente GCP que la invoca. El nivel gratuito de Gemini API es distinto de Vertex AI. |
| **Azure AI Language F0** | 5.000 *text records* gratuitos/mes compartidos entre funciones como resumen, frases clave y detección de PII; 1 record equivale aproximadamente a 1.000 caracteres. Cuando se alcanza el límite del nivel F0 se restringe el uso. [Precios oficiales](https://azure.microsoft.com/en-us/pricing/details/language/), [inicio de resumen F0](https://learn.microsoft.com/en-us/azure/ai-services/language-service/summarization/quickstart). | Resumir reportes ficticios de una zona, extraer frases repetidas o detectar información personal antes de procesar textos. El resumen extractivo selecciona frases del texto, según [Microsoft Learn](https://learn.microsoft.com/en-us/azure/ai-services/language-service/summarization/how-to/summarize). | **Alternativa si Gemini Free no está disponible** o complemento si el equipo decide mostrar IA también en Azure. Probar si el plan F0 está habilitado en la suscripción. |
| **AWS Comprehend** | Ofrece 50.000 unidades de texto al mes por API elegible durante 12 meses desde el primer uso; las funciones personalizadas no tienen ese nivel gratuito. [Precios oficiales](https://aws.amazon.com/comprehend/pricing/). | Extraer frases clave, entidades o PII de reportes. Puede ayudar a un operador, aunque no genera hipótesis como un modelo generativo. | **Reserva**, solo si el `LabRole` y el laboratorio lo permiten. El nivel gratuito de una cuenta AWS convencional no garantiza disponibilidad o costo cero en AWS Academy. |
| **Google Cloud Natural Language API** | Análisis de entidades/sentimiento con las primeras 5.000 unidades mensuales a USD 0; clasificación de contenido con las primeras 30.000 unidades a USD 0, según la [tabla oficial](https://cloud.google.com/products/natural-language/pricing). | Tendencias de texto y entidades; sus categorías generales pueden no coincidir con los síntomas de telecomunicaciones. | Alternativa NLP si Gemini no puede usarse; validar calidad con ejemplos reales de la simulación. |

**Vertex AI/Gemini en Google Cloud** y **Amazon Bedrock** no se marcan aquí como «gratis garantizado»: sus páginas de [Google Cloud](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing) y [AWS](https://aws.amazon.com/bedrock/pricing/) describen precios por modelo/uso. El programa de prueba de GCP tiene créditos y condiciones que pueden cambiar; [su documentación](https://docs.cloud.google.com/free/docs/free-cloud-features) incluye restricciones específicas para los servicios Gemini/Vertex. Por eso el diagrama v1 usa **Gemini Developer API Free**, no Vertex AI.

## Flujo que aporta valor

1. AWS detecta 10 clientes distintos en una zona/servicio y crea el incidente `sospechado`.
2. Envía a GCP solo `incident_id`, zona ficticia, servicio, clasificación de antenas, cantidad de reportantes y horas; **sin nombre, teléfono, número de servicio ni descripción cruda**.
3. Cloud Run consulta en BigQuery hasta unos pocos incidentes históricos comparables y llama a Gemini Developer API con esos hechos. Solicita un resultado estructurado: `hipotesis`, `verificaciones`, `eventos_fuente`, `limitaciones`.
4. AWS guarda la salida como sugerencia. El operador comprueba antenas y decide confirmar/descartar; si la IA falla, el flujo determinista sigue funcionando.

Para el nivel gratuito de Gemini se usarán **datos sintéticos o depurados**, debido a la condición de uso de contenido indicada por Google. Si después se desea usar información real, habrá que revisar condiciones de privacidad y pasar a un servicio/plan adecuado antes de enviar esos datos.

## Pruebas pendientes de IA

- [ ] Ver en Google AI Studio los modelos y límites gratuitos disponibles en el proyecto del equipo; elegir uno y registrar su nombre exacto.
- [ ] Crear clave de API solo en el backend GCP y guardarla en un almacén de secretos; nunca en Amplify o GitHub.
- [ ] Probar 3 casos sintéticos: caída (`0`), saturación (`>129`) y 10 reportantes con métricas normales. Revisar que la IA exprese incertidumbre en el tercer caso.
- [ ] Medir latencia, consumo de cuota y calidad de la hipótesis; mostrar la salida en el panel del operador.
- [ ] Si falla la prueba gratuita, probar Azure AI Language F0 como alternativa y actualizar [rúbrica](rubrica-hackathon.md) y diagrama.
