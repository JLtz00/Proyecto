# Despliegue en Streamlit Community Cloud

1. Entrar a `share.streamlit.io` con la cuenta vinculada a GitHub.
2. Seleccionar `JLtz00/Proyecto`, rama `main` y archivo `streamlit_app.py`.
3. En **Advanced settings**, elegir Python 3.11.
4. En Secrets añadir (los secretos raíz se exponen como variables de entorno):

```toml
NBO_PUBLIC_DEMO = "true"
```

5. Desplegar y comprobar `?view=demo&step=0` y `?view=impact`.
6. Copiar la URL en el README y en la presentación.

El modo público oculta la Mesa persistente y expone únicamente la demo aislada y la evidencia ejecutiva. No configurar claves LLM para la evaluación.
