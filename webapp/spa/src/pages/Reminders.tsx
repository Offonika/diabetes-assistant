import { useState, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { Plus, Clock, Edit2, Trash2, Bell } from 'lucide-react';
import { MedicalHeader } from '@/components/MedicalHeader';
import { useToast } from '@/hooks/use-toast';

interface Reminder {
  id: string;
  type: 'sugar' | 'insulin' | 'meal' | 'medicine';
  title: string;
  time: string;
  interval?: string;
  active: boolean;
}

interface ReminderForm {
  id?: string;
  type: keyof typeof reminderTypes;
  title: string;
  time: string;
  interval: string;
  active?: boolean;
}

const reminderTypes = {
  sugar: { label: 'Измерение сахара', icon: '🩸', color: 'medical-error' },
  insulin: { label: 'Инсулин', icon: '💉', color: 'medical-blue' },
  meal: { label: 'Приём пищи', icon: '🍽️', color: 'medical-success' },
  medicine: { label: 'Лекарства', icon: '💊', color: 'medical-teal' }
};

const Reminders = () => {
  const navigate = useNavigate();
  const { toast } = useToast();

  const [reminders, setReminders] = useState<Reminder[]>([
    {
      id: '1',
      type: 'sugar',
      title: 'Измерение сахара утром',
      time: '08:00',
      active: true
    },
    {
      id: '2',
      type: 'insulin',
      title: 'Длинный инсулин',
      time: '22:00',
      active: true
    },
    {
      id: '3',
      type: 'meal',
      title: 'Обед',
      time: '13:00',
      active: false
    }
  ]);

  const [showAddForm, setShowAddForm] = useState(false);
  const [newReminder, setNewReminder] = useState<ReminderForm>({
    type: 'sugar',
    title: '',
    time: '',
    interval: ''
  });

  const handleToggleReminder = (id: string) => {
    setReminders(prev => 
      prev.map(reminder => 
        reminder.id === id 
          ? { ...reminder, active: !reminder.active }
          : reminder
      )
    );
    toast({
      title: "Напоминание обновлено",
      description: "Статус напоминания изменен"
    });
  };

  const handleDeleteReminder = (id: string) => {
    setReminders(prev => prev.filter(reminder => reminder.id !== id));
    toast({
      title: "Напоминание удалено",
      description: "Напоминание успешно удалено"
    });
  };

  const handleSaveReminder = async (e: FormEvent) => {
    e.preventDefault();
    if (newReminder.title && newReminder.time) {
      try {
        const res = await fetch('/api/reminders', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id: newReminder.id,
            type: newReminder.type,
            title: newReminder.title,
            time: newReminder.time,
            interval: newReminder.interval || undefined
          })
        });
        const data = await res.json();
        if (!res.ok || data.status !== 'ok') {
          throw new Error('failed');
        }

        if (newReminder.id) {
          setReminders(prev =>
            prev.map(r =>
              r.id === newReminder.id
                ? { ...r, ...newReminder, interval: newReminder.interval || undefined }
                : r
            )
          );
          toast({
            title: 'Напоминание обновлено',
            description: 'Изменения сохранены'
          });
        } else {
          setReminders(prev => [
            ...prev,
            {
              id: String(data.id),
              ...newReminder,
              interval: newReminder.interval || undefined,
              active: true
            }
          ]);
          toast({
            title: 'Напоминание добавлено',
            description: 'Новое напоминание создано'
          });
        }

        setNewReminder({ type: 'sugar', title: '', time: '', interval: '' });
        setShowAddForm(false);
      } catch {
        toast({
          title: 'Ошибка',
          description: 'Не удалось сохранить напоминание',
          variant: 'destructive'
        });
      }
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <MedicalHeader 
        title="Напоминания" 
        showBack 
        onBack={() => navigate('/')}
      >
        <button
          onClick={() => {
            setNewReminder({ type: 'sugar', title: '', time: '', interval: '' });
            setShowAddForm(true);
          }}
          className="p-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 active:scale-95 transition-all duration-200"
        >
          <Plus className="w-5 h-5" />
        </button>
      </MedicalHeader>
      
      <main className="container mx-auto px-4 py-6">
        {/* Список напоминаний */}
        <div className="space-y-3 mb-6">
          {reminders.map((reminder, index) => {
            const typeInfo = reminderTypes[reminder.type];
            return (
              <div
                key={reminder.id}
                className={`medical-list-item ${!reminder.active ? 'opacity-60' : ''}`}
                style={{ animationDelay: `${index * 100}ms` }}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 flex-1">
                    <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${
                      typeInfo.color === 'medical-error' ? 'bg-medical-error/10' :
                      typeInfo.color === 'medical-blue' ? 'bg-medical-blue/10' :
                      typeInfo.color === 'medical-success' ? 'bg-medical-success/10' :
                      'bg-medical-teal/10'
                    }`}>
                      <span className="text-lg">{typeInfo.icon}</span>
                    </div>
                    <div className="flex-1">
                      <h3 className="font-medium text-foreground">{reminder.title}</h3>
                      <div className="flex items-center gap-2 text-sm text-muted-foreground">
                        <Clock className="w-3 h-3" />
                        <span>{reminder.time}</span>
                        <span className="text-xs bg-secondary px-2 py-1 rounded">
                          {typeInfo.label}
                        </span>
                      </div>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleToggleReminder(reminder.id)}
                      className={`p-2 rounded-lg transition-all duration-200 ${
                        reminder.active 
                          ? 'bg-success/10 text-success' 
                          : 'bg-secondary text-muted-foreground'
                      }`}
                    >
                      <Bell className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => {
                        setNewReminder({
                          id: reminder.id,
                          type: reminder.type,
                          title: reminder.title,
                          time: reminder.time,
                          interval: reminder.interval || '',
                          active: reminder.active
                        });
                        setShowAddForm(true);
                      }}
                      className="p-2 rounded-lg hover:bg-secondary transition-all duration-200"
                    >
                      <Edit2 className="w-4 h-4 text-muted-foreground" />
                    </button>
                    <button 
                      onClick={() => handleDeleteReminder(reminder.id)}
                      className="p-2 rounded-lg hover:bg-destructive/10 hover:text-destructive transition-all duration-200"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Форма создания/редактирования */}
        {showAddForm && (
          <form
            className="medical-card animate-scale-in"
            onSubmit={handleSaveReminder}
          >
            <h3 className="font-semibold text-foreground mb-4">
              {newReminder.id ? 'Редактирование напоминания' : 'Новое напоминание'}
            </h3>

            <div className="space-y-4">
              {/* Тип напоминания */}
              <div>
                <label className="block text-sm font-medium text-foreground mb-2">
                  Тип напоминания
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      setNewReminder(prev => ({ ...prev, type: 'sugar' }))
                    }
                    className={`p-3 rounded-lg border transition-all duration-200 ${
                      newReminder.type === 'sugar'
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border hover:bg-secondary/50'
                    }`}
                  >
                    <div className="text-lg mb-1">{reminderTypes.sugar.icon}</div>
                    <div className="text-xs">{reminderTypes.sugar.label}</div>
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setNewReminder(prev => ({ ...prev, type: 'insulin' }))
                    }
                    className={`p-3 rounded-lg border transition-all duration-200 ${
                      newReminder.type === 'insulin'
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border hover:bg-secondary/50'
                    }`}
                  >
                    <div className="text-lg mb-1">{reminderTypes.insulin.icon}</div>
                    <div className="text-xs">{reminderTypes.insulin.label}</div>
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setNewReminder(prev => ({ ...prev, type: 'meal' }))
                    }
                    className={`p-3 rounded-lg border transition-all duration-200 ${
                      newReminder.type === 'meal'
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border hover:bg-secondary/50'
                    }`}
                  >
                    <div className="text-lg mb-1">{reminderTypes.meal.icon}</div>
                    <div className="text-xs">{reminderTypes.meal.label}</div>
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setNewReminder(prev => ({ ...prev, type: 'medicine' }))
                    }
                    className={`p-3 rounded-lg border transition-all duration-200 ${
                      newReminder.type === 'medicine'
                        ? 'border-primary bg-primary/10 text-primary'
                        : 'border-border hover:bg-secondary/50'
                    }`}
                  >
                    <div className="text-lg mb-1">{reminderTypes.medicine.icon}</div>
                    <div className="text-xs">{reminderTypes.medicine.label}</div>
                  </button>
                </div>
              </div>

              {/* Название */}
              <div>
                <label className="block text-sm font-medium text-foreground mb-2">
                  Название
                </label>
                <input
                  type="text"
                  value={newReminder.title}
                  onChange={(e) => setNewReminder(prev => ({ ...prev, title: e.target.value }))}
                  className="medical-input"
                  placeholder="Например: Измерение сахара"
                />
              </div>

              {/* Время */}
              <div>
                <label className="block text-sm font-medium text-foreground mb-2">
                  Время
                </label>
                <input
                  type="time"
                  value={newReminder.time}
                  onChange={(e) => setNewReminder(prev => ({ ...prev, time: e.target.value }))}
                  className="medical-input"
                />
              </div>

              {/* Кнопки */}
              <div className="flex gap-3 pt-2">
                <button type="submit" className="medical-button flex-1">
                  Сохранить
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowAddForm(false);
                    setNewReminder({ type: 'sugar', title: '', time: '', interval: '' });
                  }}
                  className="medical-button-secondary flex-1"
                >
                  Отмена
                </button>
              </div>
            </div>
          </form>
        )}

        {/* Пустое состояние */}
        {reminders.length === 0 && (
          <div className="text-center py-12">
            <Clock className="w-16 h-16 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-medium text-foreground mb-2">
              Нет напоминаний
            </h3>
            <p className="text-muted-foreground mb-6">
              Добавьте первое напоминание для контроля диабета
            </p>
            <button
              onClick={() => {
                setNewReminder({ type: 'sugar', title: '', time: '', interval: '' });
                setShowAddForm(true);
              }}
              className="medical-button"
            >
              Создать напоминание
            </button>
          </div>
        )}
      </main>
    </div>
  );
};

export default Reminders;
