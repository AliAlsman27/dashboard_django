from django.shortcuts import render
from .forms import userform
# Create your views here.
def register(request):
    if request.method == 'POST':
        form = userform(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login')
    else:
        form = userform()
    return render(request, 'register.html', {'form': form})